import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const cli=new URL('../cli.mjs',import.meta.url);
test('help discloses owner AWS CloudShell and scopes without starting any flow',()=>{
 const r=spawnSync(process.execPath,[cli.pathname,'--help'],{encoding:'utf8',env:{PATH:process.env.PATH}});
 assert.equal(r.status,0);assert.match(r.stdout,/AWS CloudShell/);assert.match(r.stdout,/Mail.Read User.Read openid profile offline_access/);assert.equal(r.stderr,'');
});
test('unknown flags and noninteractive use fail before AWS/auth without raw stack',()=>{
 for(const args of [['--secret','arbitrary'],[]]){
  const r=spawnSync(process.execPath,[cli.pathname,...args],{encoding:'utf8',env:{PATH:process.env.PATH}});
  assert.equal(r.status,1);assert.ok(!r.stderr.includes('file://'));assert.ok(!r.stderr.includes(' at '));assert.ok(!r.stdout.includes('Device code'));assert.match(r.stderr,/Bootstrap stopped/);
 }
});
test('all SDK clients use us-east-1 and one explicit shared credential provider',async()=>{
 const subject=await import('../aws.mjs').catch(e=>{if(e.code==='ERR_MODULE_NOT_FOUND')return {};throw e;});
 assert.equal(typeof subject.createClients,'function');
 const creds={accessKeyId:'SYNTHETIC',secretAccessKey:'SYNTHETIC'},provider=async()=>creds;
 const clients=subject.createClients(provider);
 for(const client of Object.values(clients)){
  assert.equal(await client.config.region(),'us-east-1');assert.equal((await client.config.credentials()).accessKeyId,'SYNTHETIC');client.destroy();
 }
});
