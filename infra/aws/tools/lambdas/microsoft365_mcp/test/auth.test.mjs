import {test} from 'node:test';import assert from 'node:assert/strict';
const tenant='9188040d-6c67-4c5b-b112-36a304b66dad';
export const config={secretArn:'arn:aws:secretsmanager:us-east-1:123456789012:secret:owner-abc',ownerId:'synthetic.'+tenant,clientId:'00000000-0000-0000-0000-000000000001'};
export function fixture(){return JSON.stringify({version:1,homeAccountId:config.ownerId,cache:JSON.stringify({Account:{[config.ownerId+'-login.microsoftonline.com-'+tenant]:{home_account_id:config.ownerId,environment:'login.microsoftonline.com',realm:tenant,local_account_id:'synthetic-local-oid',username:'synthetic@outlook.com',authority_type:'MSSTS'}},AccessToken:{},RefreshToken:{[config.ownerId+'-login.microsoftonline.com-refreshtoken-'+config.clientId+'--']:{credential_type:'RefreshToken',home_account_id:config.ownerId,client_id:config.clientId,secret:'synthetic-not-real',environment:'login.microsoftonline.com'}},IdToken:{},AppMetadata:{}})});}
test('durable owner transaction saves rotation and exact version readback; missing warm cache fails closed',async()=>{
 const {OwnerAuth}=await import('../owner-auth.mjs');let stored=fixture(),puts=0,active=0,max=0;
 const client={send:async cmd=>{if(cmd.constructor.name==='GetSecretValueCommand')return {SecretString:stored,VersionId:'v1'}; puts++;stored=cmd.input.SecretString;return {VersionId:'v1'};}};
 const factory=async(storage)=>({getToken:async()=>{active++;max=Math.max(max,active);let cache=JSON.parse((await storage.load('token-cache')));await new Promise(r=>setTimeout(r,5));await storage.save('token-cache',JSON.stringify({...cache,AppMetadata:{rotation:puts+1}}));active--;return 'synthetic-not-real';}});
 const a=new OwnerAuth(config,client,factory);
 await Promise.all([a.run(async()=>1),a.run(async()=>2)]);assert.equal(max,1);assert.equal(puts,2);
 stored=undefined;await assert.rejects(a.run(async()=>assert.fail('must not execute')));
 stored=fixture();const old=client.send;client.send=async cmd=>cmd.constructor.name==='GetSecretValueCommand'&&cmd.input.VersionId?{SecretString:fixture(),VersionId:'v1'}:old(cmd);
 await assert.rejects(a.run(async()=>1));
});
test('cache rejects extra identity, broad permission and invalid envelope',async()=>{
 const {validateEnvelope}=await import('../owner-auth.mjs');
 assert.doesNotThrow(()=>validateEnvelope(fixture(),config));
 for(const mutate of [e=>{let c=JSON.parse(e.cache);Object.values(c.Account)[0].realm='00000000-0000-0000-0000-000000000002';e.cache=JSON.stringify(c)},e=>{let c=JSON.parse(e.cache);Object.values(c.Account)[0].home_account_id='other.'+tenant;e.cache=JSON.stringify(c)},e=>e.version=2,e=>e.homeAccountId='wrong',e=>{let c=JSON.parse(e.cache);c.Account.other={};e.cache=JSON.stringify(c)},e=>{let c=JSON.parse(e.cache);c.AccessToken.bad={...Object.values(c.RefreshToken)[0],credential_type:'AccessToken',target:'Mail.ReadWrite'};e.cache=JSON.stringify(c)}]){let e=JSON.parse(fixture());mutate(e);assert.throws(()=>validateEnvelope(JSON.stringify(e),config));}
});
