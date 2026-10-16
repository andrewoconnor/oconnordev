import {SecretsManagerClient} from '@aws-sdk/client-secrets-manager';
import {OwnerAuth} from './owner-auth.mjs';
import {createApp} from './app.mjs';
import {installGraphFetch} from './network.mjs';
import {pathToFileURL} from 'node:url';
export function runtimeConfig(env=process.env){
 const config={secretArn:env.SECRET_ARN,ownerId:env.EXPECTED_HOME_ACCOUNT_ID,username:env.EXPECTED_USERNAME,clientId:env.M365_CLIENT_ID};
 if(!/^arn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+$/.test(config.secretArn??'')||!/^[-A-Za-z0-9._]{1,256}$/.test(config.ownerId??'')||!config.ownerId.endsWith('.9188040d-6c67-4c5b-b112-36a304b66dad')||!/^[0-9a-f-]{36}$/i.test(config.clientId??''))throw Error('Invalid runtime configuration');
 return config;
}
export function start(){
 let owner;
 try{const config=runtimeConfig();owner=new OwnerAuth(config,new SecretsManagerClient({maxAttempts:1,requestHandler:{requestTimeout:10000,connectionTimeout:2000}}));}catch{owner={run:async()=>{throw Error('Unavailable');}};}
 installGraphFetch();
 const app=createApp(owner);app.requestTimeout=15000;app.headersTimeout=5000;
 app.listen(8080,'127.0.0.1');return app;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)start();
