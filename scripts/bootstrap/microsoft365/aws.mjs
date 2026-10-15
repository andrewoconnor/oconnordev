import {STSClient} from '@aws-sdk/client-sts';
import {SecretsManagerClient} from '@aws-sdk/client-secrets-manager';
import {LambdaClient} from '@aws-sdk/client-lambda';
import {defaultProvider} from '@aws-sdk/credential-provider-node';
import {REGION} from './bootstrap.mjs';
export function createClients(credentials=defaultProvider()){
 const config={region:REGION,credentials,maxAttempts:1};
 return {sts:new STSClient(config),secrets:new SecretsManagerClient(config),lambda:new LambdaClient(config)};
}
