import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { heightToNormal } from '../lib/height-to-normal.mjs';

test('flat height points outward', () => {
  assert.deepEqual([...heightToNormal(Buffer.alloc(12, 50), 4, 3, 4)], Array(12).fill([128,128,255]).flat());
});
test('horizontal slope and periodic seam', () => {
  const n=heightToNormal(Buffer.from([0,50,100,150]),4,1,4);
  assert.ok(n[3] < 128); assert.ok(n[0] > 128); assert.equal(n[0],n[9]);
});
test('vertical slope clamps bounds; flip-y reverses green only', () => {
  const data=Buffer.from([0,0,50,50,100,100]);
  const a=heightToNormal(data,2,3,4), b=heightToNormal(data,2,3,4,true);
  assert.ok(a[1]<128); assert.ok(b[1]>128);
  for(let i=0;i<a.length;i+=3){ assert.equal(a[i],b[i]); assert.equal(a[i+2],b[i+2]); }
});
test('rejects invalid dimensions, lengths and strengths', () => {
  for(const args of [[Buffer.alloc(1),0,1,1],[Buffer.alloc(1),1.5,1,1],[Buffer.alloc(2),1,1,1],[Buffer.alloc(1),1,1,NaN],[Buffer.alloc(1),1,1,-1]]) assert.throws(()=>heightToNormal(...args));
});
test('CLI refuses a directory alias that would overwrite its input', () => {
 const dir=mkdtempSync(join(tmpdir(),'normal-alias-'));
 try {
  const input=join(dir,'in'),alias=join(dir,'alias');writeFileSync(input,Buffer.from([17,23]));symlinkSync(dir,alias);
  const r=spawnSync(process.execPath,[new URL('../lib/height-to-normal.mjs',import.meta.url).pathname,'2','1','4',input,join(alias,'in')]);
  assert.notEqual(r.status,0);assert.match(r.stderr.toString(),/input and output must differ/);assert.deepEqual(readFileSync(input),Buffer.from([17,23]));
 } finally {rmSync(dir,{recursive:true,force:true});}
});
test('CLI validation preserves an existing output', () => {
  const dir=mkdtempSync(join(tmpdir(),'normal-test-'));
  try { const input=join(dir,'in'),out=join(dir,'out'); writeFileSync(input,Buffer.alloc(2));writeFileSync(out,'intact');
    const r=spawnSync(process.execPath,[new URL('../lib/height-to-normal.mjs',import.meta.url).pathname,'1','1','4',input,out]);
    assert.notEqual(r.status,0); assert.equal(readFileSync(out,'utf8'),'intact');
    const ok=spawnSync(process.execPath,[new URL('../lib/height-to-normal.mjs',import.meta.url).pathname,'2','1','4',input,out]);
    assert.equal(ok.status,0,ok.stderr.toString()); assert.equal(readFileSync(out).length,6);
  } finally {rmSync(dir,{recursive:true,force:true});}
});
