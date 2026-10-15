import {GetSecretValueCommand,PutSecretValueCommand} from '@aws-sdk/client-secrets-manager';
import {loadUpstream} from './upstream.mjs';
import {boundedFetch,currentSignal} from './network.mjs';
export const tenant='9188040d-6c67-4c5b-b112-36a304b66dad';
export const scopes=['Mail.Read','User.Read','openid','profile','offline_access'];
function scopeAllowed(s){return scopes.includes(s.replace(/^https:\/\/graph\.microsoft\.com\//i,''));}
export function validateEnvelope(raw,config){
 if(typeof raw!=='string'||Buffer.byteLength(raw)>65536)throw Error('Invalid cache');
 const e=JSON.parse(raw);
 if(e.version!==1||e.homeAccountId!==config.ownerId||typeof e.cache!=='string'||Object.keys(e).some(k=>!['version','homeAccountId','cache'].includes(k)))throw Error('Invalid envelope');
 const c=JSON.parse(e.cache),accounts=Object.values(c.Account??{});
 if(accounts.length!==1)throw Error('Invalid accounts');
 const a=accounts[0];
 if(a.home_account_id!==config.ownerId||a.realm!==tenant||!['login.microsoftonline.com','login.windows.net'].includes(a.environment)||(config.username&&a.username?.toLowerCase()!==config.username.toLowerCase()))throw Error('Wrong owner');
 for(const group of ['AccessToken','RefreshToken','IdToken'])for(const t of Object.values(c[group]??{})){
  if(t.home_account_id!==config.ownerId||t.client_id!==config.clientId||!['login.microsoftonline.com','login.windows.net'].includes(t.environment)||(t.realm&&t.realm!==tenant))throw Error('Invalid token owner');
  if(t.target&&!t.target.split(' ').every(scopeAllowed))throw Error('Broad scope');
  if(t.roles)throw Error('Application role');
 }
 return e;
}
export async function makeAuth(storage,config,networkOverride){
 const {Auth}=await loadUpstream();
 const networkClient={};
 for(const [name,method] of [['sendGetRequestAsync','GET'],['sendPostRequestAsync','POST']])networkClient[name]=async(url,opts)=>{
  const u=new URL(url);if(u.origin!=='https://login.microsoftonline.com'||u.username||u.password||!/^\/(consumers|common)\/(?:v2\.0\/\.well-known\/openid-configuration|oauth2\/v2\.0\/token|discovery\/instance)$/.test(u.pathname))throw Error('Authority boundary');
  const r=await boundedFetch(url,{method,headers:opts.headers,body:opts.body});return {status:r.status,headers:Object.fromEntries(r.headers),body:await r.json()};
 };
 const auth=new Auth({auth:{clientId:config.clientId,authority:'https://login.microsoftonline.com/consumers'},system:{networkClient:networkOverride??networkClient,loggerOptions:{loggerCallback:()=>{},piiLoggingEnabled:false}}},scopes,{expectedHomeAccountId:config.ownerId,expectedUsername:config.username},storage);
 auth.getToken=async()=>{
  const accounts=await auth.msalApp.getTokenCache().getAllAccounts();
  if(accounts.length!==1||accounts[0].homeAccountId!==config.ownerId||accounts[0].tenantId!==tenant)throw Error('Owner unavailable');
  const r=await auth.msalApp.acquireTokenSilent({account:accounts[0],scopes,forceRefresh:false});
  if(!r?.accessToken||r.account?.homeAccountId!==config.ownerId||!r.expiresOn||r.expiresOn.getTime()<Date.now()+30000||!r.scopes?.every(scopeAllowed)||!r.scopes.some(s=>s.replace(/^https:\/\/graph\.microsoft\.com\//i,'')==='Mail.Read'))throw Error('Token rejected');
  // JWT metadata is an additional local check, never a substitute for Graph signature validation.
  if(r.accessToken.split('.').length===3){const claims=JSON.parse(Buffer.from(r.accessToken.split('.')[1],'base64url'));if(claims.roles||claims.tid!==tenant||!claims.scp?.split(' ').every(scopeAllowed))throw Error('Token grants rejected');}
  return r.accessToken;
 };
 auth.getTokenForAccount=async(account)=>{if(account)throw Error('Account selection forbidden');return auth.getToken();};
 return auth;
}
export class OwnerAuth {
 constructor(config,client,factory=makeAuth){this.config=config;this.client=client;this.factory=factory;this.tail=Promise.resolve();}
 run(fn){const result=this.tail.then(()=>this.transaction(fn));this.tail=result.catch(()=>{});return result;}
 async transaction(fn){
  const send=async cmd=>{const signal=currentSignal();signal?.throwIfAborted();return this.client.send(cmd,{abortSignal:signal});};
  let auth;
  try{
   const load=async()=>{const r=await send(new GetSecretValueCommand({SecretId:this.config.secretArn}));return validateEnvelope(r.SecretString,this.config);};
   let envelope=await load();
   const storage={failClosed:true,load:async key=>key==='token-cache'?(envelope=await load()).cache:undefined,save:async(key,value)=>{
    if(key!=='token-cache')throw Error('Unsupported cache write');
    const {unwrap}=await loadUpstream();const cache=unwrap(value).data;
    const raw=JSON.stringify({version:1,homeAccountId:this.config.ownerId,cache});validateEnvelope(raw,this.config);
    const saved=await send(new PutSecretValueCommand({SecretId:this.config.secretArn,SecretString:raw}));
    if(!saved.VersionId)throw Error('Missing version');
    const check=await send(new GetSecretValueCommand({SecretId:this.config.secretArn,VersionId:saved.VersionId}));
    if(check.VersionId!==saved.VersionId||check.SecretString!==raw)throw Error('Durability failure');envelope=validateEnvelope(check.SecretString,this.config);
   },delete:async()=>{throw Error('Delete forbidden');}};
   auth=await this.factory(storage,this.config);
   // Preflight acquires/refreshes under the same serialized transaction as tool execution.
   const token=await auth.getToken();
   const fixed={getToken:async()=>token,getTokenForAccount:async a=>{if(a)throw Error('Account forbidden');return token;},isOAuthModeEnabled:()=>false,isMultiAccount:async()=>false};
   return await fn(fixed);
  }finally{
   if(auth){auth.accessToken=null;auth.tokenExpiry=null;auth.msalApp?.getTokenCache().deserialize('{}');}
  }
 }
}
