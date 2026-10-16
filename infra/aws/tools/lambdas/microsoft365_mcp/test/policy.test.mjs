import {test} from 'node:test';
import assert from 'node:assert/strict';
test('strict argument policy forwards only five bounded mail operations',async()=>{
 const {manifest,prepare}=await import('../policy.mjs');
 assert.equal(manifest.length,5);
 assert.equal(prepare('list-mail-messages',{top:2}).top,2);
 assert.equal(prepare('get-mail-message',{messageId:'abc-_123='}).messageId,'abc-_123=');
 for(const [name,args] of [['login',{}],['get-mail-message',{messageId:'../drive'}],['get-mail-message',{messageId:'%2f'}],['list-mail-messages',{top:51}],['list-mail-messages',{skip:501}],['list-mail-messages',{expand:'attachments'}],['list-mail-messages',{url:'https://evil.invalid'}],['list-mail-messages',{search:'" OR from:someone'}],['list-mail-messages',{filter:'isRead eq false'}],['list-mail-messages',{headers:{}}]]) assert.throws(()=>prepare(name,args));
 assert.equal(prepare('list-mail-messages',{search:'hello world'}).search,'"hello world"');
 assert.equal(prepare('list-mail-messages',{}).fetchAllPages,false);
 for(const key of ['constructor','toString','__proto__'])assert.throws(()=>prepare('list-mail-messages',JSON.parse(`{"${key}":"not-a-schema-property"}`)),`reject inherited property ${key}`);
 for(const t of manifest)assert.equal(t.inputSchema.additionalProperties,false);
});
