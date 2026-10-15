#!/usr/bin/env node
import {createInterface} from 'node:readline/promises';
let stage='preflight',rl,clients;
try{
 if(Number(process.versions.node.split('.')[0])<22)throw Error('Unsupported Node');
 const args=process.argv.slice(2);
 if(args.length===1&&args[0]==='--help'){
  console.log('Owner-only AWS CloudShell (TOOLS 421680664125, us-east-1), NOT Google Cloud Shell or Hermes credentials. Node >=22.');
  console.log('Usage: node scripts/bootstrap/microsoft365/cli.mjs [--client-id <explicitly reviewed public application UUID>]');
  console.log('Default client: 084a3e9f-a9f4-43f7-89f9-d229cf97853e. Consumer delegated scopes: Mail.Read User.Read openid profile offline_access.');
  console.log('Two interactive approvals; new memory-only device flow; empty fixed secret only; absent Lambda required. Never paste codes into chat.');
 }else{
  if(args.length&&!(args.length===2&&args[0]==='--client-id'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(args[1])))throw Error('Invalid arguments');
  if(!process.stdin.isTTY||!process.stdout.isTTY)throw Error('Interactive owner terminal required');
  const [{bootstrap},{authenticateConsumer},{createClients}]=await Promise.all([import('./bootstrap.mjs'),import('./microsoft.mjs'),import('./aws.mjs')]);
  rl=createInterface({input:process.stdin,output:process.stdout});clients=createClients();
  await bootstrap({...clients,clientId:args[1],authenticate:async(...a)=>{stage='Microsoft consent';return authenticateConsumer(...a);},print:s=>console.log(s),confirm:async text=>{
   stage='owner approval';const yes=(await rl.question(`${text}\nType YES to continue (anything else cancels): `))==='YES';stage='AWS/cache verification';return yes;
  }});
 }
}catch{
 // Never serialize provider errors, request objects, token responses or stacks.
 console.error(`Bootstrap stopped during ${stage}. No error payload is printed. Check Node >=22, arguments, interactive terminal, TOOLS identity/permissions, empty secret and absent Lambda. If a write may have occurred, inspect version metadata only; do not retry over existing versions.`);
 process.exitCode=1;
}finally{
 rl?.close();if(clients)for(const c of Object.values(clients))c.destroy();
}
