// Owner-only CLI core. Importing does not start authentication or access AWS.
import {randomUUID} from 'node:crypto';
import {GetCallerIdentityCommand} from '@aws-sdk/client-sts';
import {DescribeSecretCommand,PutSecretValueCommand,GetSecretValueCommand} from '@aws-sdk/client-secrets-manager';
import {GetFunctionCommand} from '@aws-sdk/client-lambda';
import {validateEnvelope,tenant,scopes} from '../../../infra/aws/tools/lambdas/microsoft365_mcp/owner-auth.mjs';
export const ACCOUNT='421680664125';
export const REGION='us-east-1';
export const SECRET_ARN='arn:aws:secretsmanager:us-east-1:421680664125:secret:/hermes/microsoft365/msal-cache-CnJLNM';
export const FUNCTION_NAME='hermes-microsoft365-mcp';
export const CLIENT_ID='084a3e9f-a9f4-43f7-89f9-d229cf97853e';
export async function bootstrap({sts,secrets,lambda,authenticate,confirm,print,clientId=CLIENT_ID}){
 let session,raw;
 try{
  if(typeof clientId!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(clientId))throw Error('Invalid client UUID');
  const identity=await sts.send(new GetCallerIdentityCommand({}));
  if(identity.Account!==ACCOUNT||typeof identity.Arn!=='string'||!identity.Arn.startsWith(`arn:aws:`)||identity.Arn.split(':')[4]!==ACCOUNT)throw Error('Wrong AWS account');
  print(`AWS identity: ${identity.Arn}; account ${ACCOUNT}; region ${REGION}`);
  const emptyAndInactive=async()=>{
   const metadata=await secrets.send(new DescribeSecretCommand({SecretId:SECRET_ARN}));
   if(metadata.ARN!==SECRET_ARN||metadata.DeletedDate||Object.keys(metadata.VersionIdsToStages??{}).length)throw Error('Secret is not empty');
   try{await lambda.send(new GetFunctionCommand({FunctionName:FUNCTION_NAME}));}catch(e){if(e.name==='ResourceNotFoundException')return;throw e;}
   throw Error('Runtime exists');
  };
  await emptyAndInactive();
  print(`Consumer delegated consent only. Client: ${clientId}. Authority: https://login.microsoftonline.com/consumers`);
  print('Scopes: Mail.Read (read mail); User.Read (basic own profile); openid (sign-in); profile (identity claims); offline_access (refresh without signing in again). No mail writes or application permissions.');
  print(`Writes ONE new cache version to ${SECRET_ARN}. No Graph/mailbox calls or local cache reads. Stop all competing writers; metadata checks are NOT atomic compare-and-swap.`);
  if(!await confirm('I approve these scopes/client and this write, and have stopped all other writers'))throw Error('Cancelled');
  session=await authenticate(clientId,({verificationUri,userCode})=>{
   if(!['https://microsoft.com/devicelogin','https://www.microsoft.com/link'].includes(verificationUri)||typeof userCode!=='string'||!/^[A-Z0-9-]{4,32}$/.test(userCode))throw Error('Invalid device instructions');
   print(`Microsoft sign-in: ${verificationUri}`);print(`Device code (enter only at Microsoft, never in chat): ${userCode}`);
  });
  const account=session.result?.account;
  if(!account||account.tenantId!==tenant||typeof account.homeAccountId!=='string'||!new RegExp(`^[A-Za-z0-9_-]+\\.${tenant}$`).test(account.homeAccountId)||typeof account.username!=='string'||!account.username||/[\x00-\x1f\x7f]/.test(account.username))throw Error('Invalid consumer identity');
  const normalize=s=>s.replace(/^https:\/\/graph\.microsoft\.com\//i,'');
  if(!session.result.accessToken||!Array.isArray(session.result.scopes)||!session.result.scopes.every(s=>typeof s==='string'&&scopes.includes(normalize(s)))||!['Mail.Read','User.Read'].every(s=>session.result.scopes.map(normalize).includes(s)))throw Error('Invalid token result grants');
  raw=JSON.stringify({version:1,homeAccountId:account.homeAccountId,cache:session.serialize()});
  validateEnvelope(raw,{ownerId:account.homeAccountId,clientId});
  const cache=JSON.parse(JSON.parse(raw).cache);
  const grantsOK=target=>typeof target==='string'&&target.split(' ').every(s=>scopes.includes(normalize(s)))&&['Mail.Read','User.Read'].every(s=>target.split(' ').map(normalize).includes(s));
  if(!Object.values(cache.RefreshToken??{}).some(t=>typeof t.secret==='string'&&t.secret.length)||!Object.values(cache.AccessToken??{}).some(t=>t.secret&&grantsOK(t.target)))throw Error('Missing refresh or approved access token');
  print(`Microsoft identity: ${account.username}; homeAccountId: ${account.homeAccountId}; client: ${clientId}`);
  if(!await confirm('This is my intended personal account; approve storing its cache now'))throw Error('Cancelled');
  await emptyAndInactive();
  const token=randomUUID();
  const saved=await secrets.send(new PutSecretValueCommand({SecretId:SECRET_ARN,ClientRequestToken:token,SecretString:raw,VersionStages:['AWSCURRENT']}));
  if(saved.VersionId!==token)throw Error('Write version mismatch');
  const readback=await secrets.send(new GetSecretValueCommand({SecretId:SECRET_ARN,VersionId:token}));
  if(readback.VersionId!==token||readback.SecretString!==raw)throw Error('Readback mismatch');
  validateEnvelope(readback.SecretString,{ownerId:account.homeAccountId,clientId});
  print('Cache stored and exact version readback verified. Runtime remains disabled.');
  print(`microsoft365_owner_home_account_id = "${account.homeAccountId}"`);
  print(`microsoft365_client_id = "${clientId}"`);
  print('Select the latest separately verified published image digest before the separate activation review.');
  return {ownerId:account.homeAccountId,clientId};
 }finally{await session?.clear();raw=undefined;}
}
