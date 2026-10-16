import {PublicClientApplication} from '@azure/msal-node';
import {scopes} from '../../../infra/aws/tools/lambdas/microsoft365_mcp/owner-auth.mjs';
// Optional network dependency is used only by offline tests, never CLI flags/env.
export async function authenticateConsumer(clientId,display,networkClient){
 const app=new PublicClientApplication({auth:{clientId,authority:'https://login.microsoftonline.com/consumers'},system:{...(networkClient?{networkClient}:{}),loggerOptions:{loggerCallback:()=>{},piiLoggingEnabled:false,logLevel:0}}});
 const cache=app.getTokenCache();
 const clear=async()=>{for(const account of await cache.getAllAccounts())await cache.removeAccount(account);cache.deserialize('{}');};
 try{
  const result=await app.acquireTokenByDeviceCode({scopes:[...scopes],deviceCodeCallback:r=>display({verificationUri:r.verificationUri,userCode:r.userCode})});
  return {result,serialize:()=>cache.serialize(),clear:async()=>{await clear();if(result){result.accessToken='';result.idToken='';}}};
 }catch(e){await clear();throw e;}
}
