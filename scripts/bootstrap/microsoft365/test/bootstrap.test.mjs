import {test} from 'node:test';
import assert from 'node:assert/strict';
const subject=await import('../bootstrap.mjs').catch(e=>{if(e.code==='ERR_MODULE_NOT_FOUND')return {};throw e;});
const tenant='9188040d-6c67-4c5b-b112-36a304b66dad';
const clientId='084a3e9f-a9f4-43f7-89f9-d229cf97853e';
const ownerId=`synthetic.${tenant}`;
function fixture(){
 const token={home_account_id:ownerId,client_id:clientId,environment:'login.microsoftonline.com',realm:tenant,secret:'SYNTHETIC-SECRET',target:'Mail.Read User.Read openid profile offline_access'};
 return {Account:{one:{home_account_id:ownerId,realm:tenant,environment:'login.microsoftonline.com',username:'synthetic@outlook.com'}},AccessToken:{one:token},RefreshToken:{one:{...token}},IdToken:{one:{...token}}};
}
function harness(){
 const events=[],logs=[];let stored,cache=fixture(),cleared=false;
 const deps={
  print:s=>logs.push(s),confirm:async()=>true,
  sts:{send:async c=>{events.push(c.constructor.name);return {Account:'421680664125',Arn:'arn:aws:sts::421680664125:assumed-role/Owner/session'};}},
  lambda:{send:async c=>{events.push(c.constructor.name);throw Object.assign(Error('not deployed'),{name:'ResourceNotFoundException'});}},
  secrets:{send:async c=>{events.push(c.constructor.name);if(c.constructor.name==='DescribeSecretCommand')return {ARN:'arn:aws:secretsmanager:us-east-1:421680664125:secret:/hermes/microsoft365/msal-cache-CnJLNM',VersionIdsToStages:{}};if(c.constructor.name==='PutSecretValueCommand'){stored=c.input;return {VersionId:c.input.ClientRequestToken};}return {VersionId:stored.ClientRequestToken,SecretString:stored.SecretString};}},
  authenticate:async(id,callback)=>{events.push('authenticate');callback({verificationUri:'https://microsoft.com/devicelogin',userCode:'SYNTHETIC-CODE'});return {result:{account:{homeAccountId:ownerId,tenantId:tenant,username:'synthetic@outlook.com'},scopes:['Mail.Read','User.Read','openid','profile','offline_access'],accessToken:'SYNTHETIC-SECRET'},serialize:()=>JSON.stringify(cache),clear:()=>{cleared=true;}};}
 };
 return {deps,events,logs,get stored(){return stored;},set cache(c){cache=c;},get cleared(){return cleared;}};
}
test('new consumer cache is confirmed, validated, written once, read back by exact version and cleared',async()=>{
 const h=harness();const result=await subject.bootstrap(h.deps);
 assert.equal(result.ownerId,ownerId);assert.equal(result.clientId,clientId);
 assert.deepEqual(h.events,['GetCallerIdentityCommand','DescribeSecretCommand','GetFunctionCommand','authenticate','DescribeSecretCommand','GetFunctionCommand','PutSecretValueCommand','GetSecretValueCommand']);
 assert.equal(JSON.parse(h.stored.SecretString).homeAccountId,ownerId);
 assert.match(h.stored.ClientRequestToken,/^[a-f0-9-]{36}$/);assert.ok(h.cleared);
 assert.ok(!h.logs.join('\n').includes('SYNTHETIC-SECRET'));
});
test('device callback rejects arbitrary links before printing anything from provider',async()=>{
 const h=harness();h.deps.authenticate=async(id,cb)=>{cb({verificationUri:'https://evil.example/devicelogin',userCode:'SAFE',message:'SYNTHETIC-SECRET'});throw Error('should not reach');};
 await assert.rejects(subject.bootstrap(h.deps),/Invalid device instructions/);
 assert.ok(!h.logs.join('\n').includes('evil.example'));assert.ok(!h.events.includes('PutSecretValueCommand'));
});
for(const variant of ['missing-refresh','empty-refresh','wrong-account','organization','broader-scopes','missing-mail','wrong-client','extra-account'])test(`reject ${variant} before storing`,async()=>{
 const h=harness(),c=fixture();
 if(variant==='missing-refresh')delete c.RefreshToken;
 if(variant==='empty-refresh')c.RefreshToken.one.secret='';
 if(variant==='wrong-account')c.Account.one.home_account_id='other';
 if(variant==='organization')c.Account.one.realm='organizations';
 if(variant==='broader-scopes')c.AccessToken.one.target+=' Mail.ReadWrite';
 if(variant==='missing-mail')c.AccessToken.one.target='User.Read';
 if(variant==='wrong-client')c.RefreshToken.one.client_id='other';
 if(variant==='extra-account')c.Account.two={...c.Account.one};
 h.cache=c;
 await assert.rejects(subject.bootstrap(h.deps));assert.ok(h.cleared);assert.ok(!h.events.includes('PutSecretValueCommand'));
});
test('omitted empty version map is valid metadata',async()=>{
 const h=harness(),send=h.deps.secrets.send;h.deps.secrets.send=async c=>{const r=await send(c);if(c.constructor.name==='DescribeSecretCommand')delete r.VersionIdsToStages;return r;};
 await subject.bootstrap(h.deps);assert.ok(h.stored);
});
for(const [name,mutate] of [
 ['wrong AWS account',h=>{h.deps.sts.send=async()=>({Account:'000000000000',Arn:'arn:aws:iam::000000000000:user/Other'});}],
 ['occupied secret',h=>{h.deps.secrets.send=async()=>({ARN:subject.SECRET_ARN,VersionIdsToStages:{existing:[]}});}],
 ['missing secret',h=>{h.deps.secrets.send=async()=>{throw Object.assign(Error('private details'),{name:'ResourceNotFoundException'});};}],
 ['deployed Lambda',h=>{h.deps.lambda.send=async()=>({Configuration:{State:'Inactive'}});}],
 ['unknown Lambda permission',h=>{h.deps.lambda.send=async()=>{throw Object.assign(Error('private details'),{name:'AccessDeniedException'});};}],
 ['declined first approval',h=>{h.deps.confirm=async()=>false;}]
])test(`${name} aborts before Microsoft and before value reads/writes`,async()=>{
 const h=harness();mutate(h);await assert.rejects(subject.bootstrap(h.deps));
 assert.ok(!h.events.includes('authenticate'));assert.ok(!h.events.includes('PutSecretValueCommand'));assert.ok(!h.events.includes('GetSecretValueCommand'));
});
test('second identity approval decline clears cache and never writes',async()=>{
 const h=harness();let n=0;h.deps.confirm=async()=>++n===1;
 await assert.rejects(subject.bootstrap(h.deps));assert.ok(h.cleared);assert.ok(!h.stored);
});
test('another writer appearing at second metadata check aborts',async()=>{
 const h=harness(),send=h.deps.secrets.send;let n=0;
 h.deps.secrets.send=async c=>{const r=await send(c);if(c.constructor.name==='DescribeSecretCommand'&&++n===2)r.VersionIdsToStages={concurrent:['AWSCURRENT']};return r;};
 await assert.rejects(subject.bootstrap(h.deps));assert.ok(h.cleared);assert.ok(!h.stored);
});
test('exact version is required for readback and failure never reports success',async()=>{
 const h=harness(),send=h.deps.secrets.send;
 h.deps.secrets.send=async c=>{const r=await send(c);if(c.constructor.name==='GetSecretValueCommand'){assert.equal(c.input.VersionId,h.stored.ClientRequestToken);r.SecretString='DIFFERENT SYNTHETIC SECRET';}return r;};
 await assert.rejects(subject.bootstrap(h.deps),/Readback mismatch/);assert.ok(h.cleared);
 assert.ok(!h.logs.join('\n').includes('stored and exact'));assert.ok(!h.logs.join('\n').includes('DIFFERENT SYNTHETIC SECRET'));
});
test('token result identity and grants must agree with consumer cache',async()=>{
 const h=harness(),authenticate=h.deps.authenticate;
 h.deps.authenticate=async(...a)=>{const s=await authenticate(...a);s.result.account.tenantId='organizations';return s;};
 await assert.rejects(subject.bootstrap(h.deps));assert.ok(!h.stored);
});
test('non-UUID client ID is rejected before AWS calls',async()=>{
 const h=harness();h.deps.clientId='not-a-uuid';await assert.rejects(subject.bootstrap(h.deps));assert.deepEqual(h.events,[]);
});
for(const phase of ['DescribeSecretCommand','PutSecretValueCommand','GetSecretValueCommand'])test(`${phase} provider errors stop without logging payloads or deleting an accepted version`,async()=>{
 const h=harness(),send=h.deps.secrets.send;
 h.deps.secrets.send=async c=>{
  if(c.constructor.name===phase){
   // Simulate an ambiguous write: the service accepts it before transport failure.
   if(phase==='PutSecretValueCommand')await send(c);
   throw Error('SYNTHETIC-PROVIDER-PRIVATE-PAYLOAD');
  }
  return send(c);
 };
 await assert.rejects(subject.bootstrap(h.deps),/SYNTHETIC-PROVIDER-PRIVATE-PAYLOAD/);
 assert.ok(!h.logs.join('\n').includes('SYNTHETIC-PROVIDER-PRIVATE-PAYLOAD'));
 assert.ok(!h.logs.join('\n').includes('stored and exact'));
 assert.ok(h.events.every(e=>!e.includes('Delete')&&!e.includes('UpdateSecretVersionStage')));
 if(phase==='DescribeSecretCommand'){assert.ok(!h.stored);assert.ok(!h.events.includes('authenticate'));}
 else {assert.ok(h.stored);assert.ok(h.cleared);assert.equal(h.events.filter(e=>e==='PutSecretValueCommand').length,1);}
});
test('Microsoft token errors are propagated only to the sanitizing CLI and never printed by core',async()=>{
 const h=harness();h.deps.authenticate=async()=>{throw Error('SYNTHETIC-TOKEN-PRIVATE-PAYLOAD');};
 await assert.rejects(subject.bootstrap(h.deps),/SYNTHETIC-TOKEN-PRIVATE-PAYLOAD/);
 assert.ok(!h.logs.join('\n').includes('SYNTHETIC-TOKEN-PRIVATE-PAYLOAD'));assert.ok(!h.stored);
});
test('owner bootstrap entry point is available without running authentication',()=>{
 assert.equal(typeof subject.bootstrap,'function');
});
