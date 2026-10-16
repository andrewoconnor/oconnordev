import http from 'node:http';
import {StreamableHTTPServerTransport} from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {CallToolRequestSchema,ListToolsRequestSchema} from '@modelcontextprotocol/sdk/types.js';
import {manifest,prepare,allowedGraphURL} from './policy.mjs';
import {withinDeadline,MAX_BYTES} from './network.mjs';
import {loadUpstream} from './upstream.mjs';
function clean(value){
 if(Array.isArray(value))return value.map(clean);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>!k.startsWith('@odata.')).map(([k,v])=>[k,clean(v)]));
 return value;
}
async function mcpServer(auth){
 const {Server}=await loadUpstream();
 const upstream=new Server(auth,{http:'127.0.0.1:8080',trustProxyAuth:true,readOnly:true,orgMode:false,discovery:false,enableAuthTools:false,enabledTools:'^('+manifest.map(t=>t.name).join('|')+')$',allowedScopes:'Mail.Read User.Read offline_access'});
 await upstream.initialize('0.166.0');
 const graph=upstream.graphClient;
 const perform=graph.performRequest.bind(graph);
 graph.performRequest=(endpoint,token,opts={})=>{allowedGraphURL('https://graph.microsoft.com/v1.0'+endpoint,opts.method??'GET');return perform(endpoint,token,{...opts,maxBytes:MAX_BYTES});};
 const request=graph.makeRequestWithMetadata.bind(graph);
 graph.makeRequestWithMetadata=async(endpoint,opts)=>{const r=await request(endpoint,{...opts,maxBytes:MAX_BYTES});r.data=clean(r.data);if(Array.isArray(r.data?.value)){const top=Number(new URL('https://graph.microsoft.com/v1.0'+endpoint).searchParams.get('$top')??10);r.data.value=r.data.value.slice(0,Math.min(50,Number.isInteger(top)&&top>0?top:10));r.metadata.result_count=r.data.value.length;delete r.metadata.result_has_more;}return r;};
 const server=upstream.createMcpServer();
 const names=Object.keys(server._registeredTools).sort();
 if(JSON.stringify(names)!==JSON.stringify(manifest.map(t=>t.name).sort()))throw Error('Upstream catalog drift');
 const call=server.server._requestHandlers.get('tools/call');
 server.server.setRequestHandler(ListToolsRequestSchema,async()=>({tools:manifest}));
 server.server.setRequestHandler(CallToolRequestSchema,async(req,extra)=>{
  try{
   const args=prepare(req.params.name,req.params.arguments??{});
   const result=await call({...req,params:{name:req.params.name,arguments:args}},extra);
   if(result.isError)throw Error('Tool failed');
   if(Buffer.byteLength(JSON.stringify(result))>MAX_BYTES)throw Error('Response too large');
   return result;
  }catch{return {isError:true,content:[{type:'text',text:'Mail operation unavailable or invalid arguments.'}]};}
 });
 return server;
}
export function createApp(owner){
 return http.createServer(async(req,res)=>{
  const send=(status,body)=>{if(!res.headersSent){res.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(body));}};
  if(req.url!=='/mcp'&&req.url!=='/health'){send(404,{error:'Not found'});return;}
  if(req.url==='/health'){
   if(req.method!=='GET'){send(405,{error:'Method not allowed'});return;}
   try{await withinDeadline(()=>owner.run(async()=>true));send(200,{status:'ready'});}catch{send(503,{status:'unavailable'});}return;
  }
  if(req.method!=='POST'){send(405,{error:'Method not allowed'});return;}
  if(!/^application\/json(?:;|$)/i.test(req.headers['content-type']??'')){send(415,{error:'JSON required'});return;}
  let server,transport;
  try{await withinDeadline(async()=>{
   const chunks=[];let size=0;
   for await(const chunk of req){size+=chunk.length;if(size>16384)throw Error('Request too large');chunks.push(chunk);}
   const body=JSON.parse(Buffer.concat(chunks));
   if(!body||Array.isArray(body)||body.jsonrpc!=='2.0'||!['initialize','notifications/initialized','ping','tools/list','tools/call'].includes(body.method))throw Error('Invalid request');
   // Validate before any secret read or refresh.
   if(body.method==='tools/call')prepare(body.params?.name,body.params?.arguments??{});
   await owner.run(async auth=>{
    server=await mcpServer(auth);
    transport=new StreamableHTTPServerTransport({sessionIdGenerator:undefined,enableJsonResponse:true});
    await server.connect(transport);await transport.handleRequest(req,res,body);
   });
  });}catch{send(503,{jsonrpc:'2.0',id:null,error:{code:-32000,message:'Mail service unavailable or invalid request'}});}
  finally{await transport?.close();await server?.close();}
 });
}
