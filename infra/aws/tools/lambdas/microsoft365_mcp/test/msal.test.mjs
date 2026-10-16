import {test} from 'node:test';import assert from 'node:assert/strict';
import {config,fixture} from './auth.test.mjs';
test('real MSAL cache plugin refresh persists rotated synthetic refresh token before success',async()=>{
 const {OwnerAuth,makeAuth,tenant}=await import('../owner-auth.mjs');let saved=fixture(),writes=0;
 const client={send:async cmd=>{if(cmd.constructor.name==='GetSecretValueCommand')return {SecretString:saved,VersionId:'synthetic-version'};saved=cmd.input.SecretString;writes++;return {VersionId:'synthetic-version'};}};
 const network={sendGetRequestAsync:async url=>{
  if(url.includes('discovery/instance'))return {status:200,headers:{},body:{tenant_discovery_endpoint:'https://login.microsoftonline.com/consumers/v2.0/.well-known/openid-configuration',metadata:[{preferred_network:'login.microsoftonline.com',preferred_cache:'login.microsoftonline.com',aliases:['login.microsoftonline.com']}]}};
  return {status:200,headers:{},body:{authorization_endpoint:'https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize',token_endpoint:'https://login.microsoftonline.com/consumers/oauth2/v2.0/token',issuer:'https://login.microsoftonline.com/'+tenant+'/v2.0',jwks_uri:'https://login.microsoftonline.com/consumers/discovery/v2.0/keys'}};
 },sendPostRequestAsync:async()=>({status:200,headers:{},body:{token_type:'Bearer',scope:'Mail.Read User.Read openid profile offline_access',expires_in:3600,ext_expires_in:3600,access_token:'synthetic-opaque-not-real',id_token:'e30.'+Buffer.from(JSON.stringify({tid:tenant,oid:'synthetic-local-oid',sub:'synthetic',aud:config.clientId,iss:'https://login.microsoftonline.com/'+tenant+'/v2.0',exp:Math.floor(Date.now()/1000)+3600,iat:Math.floor(Date.now()/1000),preferred_username:'synthetic@outlook.com'})).toString('base64url')+'.synthetic',refresh_token:'synthetic-rotated-not-real',client_info:Buffer.from(JSON.stringify({uid:'synthetic',utid:tenant})).toString('base64url')}})};
 const owner=new OwnerAuth(config,client,(storage,c)=>makeAuth(storage,c,network));
 let completed=false;await owner.run(async a=>{assert.equal(await a.getToken(),'synthetic-opaque-not-real');assert.ok(writes>0);completed=true;});
 assert.ok(completed);assert.ok(JSON.parse(saved).cache.includes('synthetic-rotated-not-real'));
});
