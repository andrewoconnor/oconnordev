import {test} from 'node:test';
import assert from 'node:assert/strict';
const subject=await import('../microsoft.mjs').catch(e=>{if(e.code==='ERR_MODULE_NOT_FOUND')return {};throw e;});
const clientId='084a3e9f-a9f4-43f7-89f9-d229cf97853e',tenant='9188040d-6c67-4c5b-b112-36a304b66dad';
test('real MSAL device flow produces cache accepted by production validator without filesystem storage or Graph',async()=>{
 assert.equal(typeof subject.authenticateConsumer,'function');
 const calls=[];
 const network={sendGetRequestAsync:async url=>{
  calls.push(url);
  if(url.includes('discovery/instance'))return {status:200,headers:{},body:{tenant_discovery_endpoint:'https://login.microsoftonline.com/consumers/v2.0/.well-known/openid-configuration',metadata:[{preferred_network:'login.microsoftonline.com',preferred_cache:'login.microsoftonline.com',aliases:['login.microsoftonline.com']}]}};
  return {status:200,headers:{},body:{authorization_endpoint:'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize',token_endpoint:'https://login.microsoftonline.com/consumers/oauth2/v2.0/token',device_authorization_endpoint:'https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode',issuer:`https://login.microsoftonline.com/${tenant}/v2.0`,jwks_uri:'https://login.microsoftonline.com/consumers/discovery/v2.0/keys'}};
 },sendPostRequestAsync:async(url,opts)=>{
  calls.push(url);const params=new URLSearchParams(opts.body);
  if(new URL(url).pathname.endsWith('/devicecode')){assert.equal(params.get('client_id'),clientId);assert.deepEqual(new Set(params.get('scope').split(' ')),new Set(['Mail.Read','User.Read','openid','profile','offline_access']));return {status:200,headers:{},body:{user_code:'FAKE-CODE',device_code:'synthetic-device-token',verification_uri:'https://microsoft.com/devicelogin',expires_in:900,interval:0,message:'MUST NOT PRINT RAW'}};}
  assert.equal(params.get('grant_type'),'device_code');
  return {status:200,headers:{},body:{token_type:'Bearer',scope:'Mail.Read User.Read openid profile offline_access',expires_in:3600,ext_expires_in:3600,access_token:'synthetic-access',refresh_token:'synthetic-refresh',client_info:Buffer.from(JSON.stringify({uid:'synthetic',utid:tenant})).toString('base64url'),id_token:'e30.'+Buffer.from(JSON.stringify({tid:tenant,oid:'DIFFERENT-OID',sub:'synthetic',aud:clientId,iss:`https://login.microsoftonline.com/${tenant}/v2.0`,exp:Math.floor(Date.now()/1000)+3600,iat:Math.floor(Date.now()/1000),preferred_username:'synthetic@outlook.com'})).toString('base64url')+'.synthetic'}};
 }};
 const callbacks=[];const session=await subject.authenticateConsumer(clientId,x=>callbacks.push(x),network);
 assert.equal(session.result.account.homeAccountId,`synthetic.${tenant}`);
 assert.deepEqual(callbacks,[{verificationUri:'https://microsoft.com/devicelogin',userCode:'FAKE-CODE'}]);
 const {validateEnvelope}=await import('../../../../infra/aws/tools/lambdas/microsoft365_mcp/owner-auth.mjs');
 const raw=JSON.stringify({version:1,homeAccountId:session.result.account.homeAccountId,cache:session.serialize()});
 validateEnvelope(raw,{ownerId:session.result.account.homeAccountId,clientId});
 assert.ok(JSON.parse(JSON.parse(raw).cache).RefreshToken);
 assert.ok(calls.every(u=>u.startsWith('https://login.microsoftonline.com/')));
 await session.clear();
 for(const group of ['Account','AccessToken','RefreshToken','IdToken'])assert.equal(Object.keys(JSON.parse(session.serialize())[group]??{}).length,0);
 assert.equal(session.result.accessToken,'');assert.equal(session.result.idToken,'');
});
