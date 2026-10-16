import {test} from 'node:test';import assert from 'node:assert/strict';
test('bounded fetch rejects oversize bodies, stalled bodies, external and escaped Graph URLs',async()=>{
 const {boundedFetch,withinDeadline}=await import('../network.mjs');
 const {allowedGraphURL}=await import('../policy.mjs');
 for(const u of ['https://evil.invalid/v1.0/me/messages','https://graph.microsoft.com/v1.0/me/drive','https://graph.microsoft.com/v1.0/users/other/messages','https://graph.microsoft.com/v1.0/me/messages/a/attachments'])assert.throws(()=>allowedGraphURL(u));
 await assert.rejects(withinDeadline(()=>boundedFetch('https://graph.microsoft.com/v1.0/me/messages',{},async()=>new Response('a'.repeat(1048577))),200));
 await assert.rejects(withinDeadline(()=>boundedFetch('https://graph.microsoft.com/v1.0/me/messages',{},async()=>new Response(new ReadableStream({start(){}}))),30));
 const {loadUpstream}=await import('../upstream.mjs'); const u=await loadUpstream();assert.equal(typeof u.Server,'function');assert.equal(typeof u.Auth,'function');
});
