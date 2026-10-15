import {AsyncLocalStorage} from 'node:async_hooks';
import {allowedGraphURL} from './policy.mjs';
const context=new AsyncLocalStorage();const nativeFetch=globalThis.fetch;
export const MAX_BYTES=1048576;
export function currentSignal(){return context.getStore()?.signal;}
export async function withinDeadline(fn,ms=15000){
 const controller=new AbortController();let timer;
 const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(Error('Deadline'));},ms);});
 try{return await context.run({signal:controller.signal},()=>Promise.race([fn(),timeout]));}finally{clearTimeout(timer);controller.abort();}
}
export async function boundedFetch(url,options={},fetcher=nativeFetch){
 const u=new URL(url);
 if(u.hostname==='graph.microsoft.com')allowedGraphURL(url,options.method??'GET');
 const signal=AbortSignal.any([currentSignal()??AbortSignal.timeout(15000),...(options.signal?[options.signal]:[])]);
 const abort=new Promise((_,reject)=>{if(signal.aborted)reject(Error('Deadline'));else signal.addEventListener('abort',()=>reject(Error('Deadline')),{once:true});});
 return Promise.race([abort,(async()=>{
  const r=await fetcher(url,{...options,signal,redirect:'error'});
  if(Number(r.headers.get('content-length'))>MAX_BYTES){await r.body?.cancel();throw Error('Response too large');}
  const reader=r.body?.getReader(),chunks=[];let size=0;
  while(reader){const {done,value}=await Promise.race([reader.read(),abort]);if(done)break;size+=value.byteLength;if(size>MAX_BYTES){await reader.cancel();throw Error('Response too large');}chunks.push(value);}
  return new Response(Buffer.concat(chunks),{status:r.status,headers:r.headers});
 })()]);
}
export function installGraphFetch(fetcher=nativeFetch){globalThis.fetch=(url,opts)=>{
 if(new URL(url).origin!=='https://graph.microsoft.com')throw Error('Unexpected fetch destination');
 return boundedFetch(url,opts,fetcher);
};}
