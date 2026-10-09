import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
const cli=new URL('../manifest.mjs',import.meta.url).pathname;
test('capture hashes actual bytes and verify rejects corruption, missing files and empty manifests',()=>{
 const dir=mkdtempSync(join(tmpdir(),'manifest-test-'));try{
 const source=join(dir,'source'),target=join(dir,'target'),spec=join(dir,'spec.json'),manifest=join(dir,'manifest.json');
 writeFileSync(source,'actual test bytes');writeFileSync(target,'derived fixture');
 writeFileSync(spec,JSON.stringify({sources:[{id:'height',path:'source',location:'local test fixture'}],derived:[{path:'target',sources:['height'],options:{strength:4}}],tools:[{name:'node',command:process.execPath,args:['--version']}]}));
 const run=(...args)=>spawnSync(process.execPath,[cli,...args],{encoding:'utf8'});
 assert.equal(run('capture',spec,manifest).status,0);const data=JSON.parse(readFileSync(manifest));assert.match(data.sources[0].sha256,/^[a-f0-9]{64}$/);assert.equal(data.sources[0].size,17);assert.ok(data.tools.node.startsWith('v'));assert.equal(run('verify',manifest).status,0);
 writeFileSync(source,'changed');assert.notEqual(run('verify',manifest).status,0);rmSync(source);assert.notEqual(run('verify',manifest).status,0);
 writeFileSync(manifest,JSON.stringify({schemaVersion:1,sources:[],derived:[],tools:{}}));assert.notEqual(run('verify',manifest).status,0);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
