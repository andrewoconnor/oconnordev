import {test} from 'node:test';import assert from 'node:assert/strict';
test('real upstream MCP HTTP exposes exact tools and routes; defensive Graph requests never paginate',async()=>{
 const {createApp}=await import('../app.mjs');const {installGraphFetch}=await import('../network.mjs');
 const fetch=globalThis.fetch;let calls=[];installGraphFetch(async(url,opts)=>{calls.push({url:String(url),method:opts?.method??'GET'});return Response.json({value:Array.from({length:60},(_,i)=>({id:'synthetic-'+i,subject:'fixture'})),'@odata.nextLink':'https://evil.invalid/v1.0/me/drive'});});
 const auth={run:async fn=>fn({isOAuthModeEnabled:()=>false,isMultiAccount:async()=>false,getToken:async()=> 'synthetic-not-real',getTokenForAccount:async()=> 'synthetic-not-real'})};
 const app=createApp(auth);await new Promise(r=>app.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${app.address().port}`;
 const request=async(method,params)=>{const r=await fetch(base+'/mcp',{method:'POST',headers:{'content-type':'application/json',accept:'application/json, text/event-stream'},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});assert.equal(r.headers.get('mcp-session-id'),null);return r.json();};
 try{
  assert.equal((await fetch(base+'/health')).status,200);
  for(const p of ['/authorize','/token','/.well-known/oauth-authorization-server','/attachments','/'])assert.equal((await fetch(base+p)).status,404);
  assert.equal((await fetch(base+'/mcp')).status,405);
  assert.ok((await request('initialize',{protocolVersion:'2025-03-26',capabilities:{},clientInfo:{name:'synthetic',version:'1'}})).result);
  const catalog=await request('tools/list',{});assert.equal(catalog.result.tools.length,5);
  for(const t of catalog.result.tools)assert.equal(t.inputSchema.additionalProperties,false);
  for(const [name,args] of [['login',{}],['graph-batch',{}],['list-mail-messages',{expand:'attachments'}],['get-mail-message',{messageId:'..'}],['list-mail-folders',{account:'other'}]]){const r=await request('tools/call',{name,arguments:args});assert.ok(r.error||r.result?.isError);}
  assert.equal(calls.length,0);
  for(const [name,args] of [['list-mail-messages',{top:2,search:'hello'}],['get-mail-message',{messageId:'synthetic'}],['list-mail-folders',{}],['list-mail-child-folders',{mailFolderId:'inbox'}],['list-mail-folder-messages',{mailFolderId:'inbox'}]]){
   const r=await request('tools/call',{name,arguments:args});assert.ok(!r.error&&!r.result?.isError,JSON.stringify(r));assert.ok(!JSON.stringify(r).includes('evil.invalid'));if(name!=='get-mail-message')assert.ok(JSON.parse(r.result.content[0].text).value.length<=(args.top??10));
  }
  assert.equal(calls.length,5);for(const c of calls){assert.equal(c.method,'GET');assert.ok(c.url.includes('%24select=')||c.url.includes('$select='));}
 }finally{await new Promise(r=>app.close(r));}
});
