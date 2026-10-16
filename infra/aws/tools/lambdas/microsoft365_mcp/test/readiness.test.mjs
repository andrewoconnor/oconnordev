import {test} from 'node:test';import assert from 'node:assert/strict';
test('unconfigured runtime stays unhealthy and rejects caller identity rather than bootstrapping',async()=>{
 const {runtimeConfig,start}=await import('../main.mjs');
 assert.throws(()=>runtimeConfig({}));
 const fetch=globalThis.fetch;const app=start();await new Promise(r=>app.once('listening',r));
 try{const r=await fetch('http://127.0.0.1:8080/health');assert.equal(r.status,503);assert.deepEqual(await r.json(),{status:'unavailable'});}finally{await new Promise(r=>app.close(r));}
});
