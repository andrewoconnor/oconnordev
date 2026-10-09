#!/usr/bin/env node
// No dependencies. Capture only existing files; never synthesize source hashes.
import {createHash,randomUUID} from 'node:crypto';
import {readFileSync,statSync,writeFileSync,renameSync,unlinkSync,realpathSync} from 'node:fs';
import {dirname,resolve,relative} from 'node:path';
import {spawnSync} from 'node:child_process';
const need=(ok,message)=>{if(!ok)throw new Error(message);};
const digest=file=>{need(statSync(file).isFile(),'not a regular file: '+file);const data=readFileSync(file);need(data.length>0,'empty file: '+file);return {size:data.length,sha256:createHash('sha256').update(data).digest('hex')};};
function validate(m){
 need(m.schemaVersion===1,'unsupported schema');need(Array.isArray(m.sources)&&m.sources.length>0,'actual sources are required');need(Array.isArray(m.derived),'derived list required');need(m.tools&&typeof m.tools==='object'&&!Array.isArray(m.tools),'tool versions required');
 const ids=new Set();for(const s of m.sources){need(typeof s.id==='string'&&s.id.length>0&&!ids.has(s.id),'invalid/duplicate source id');ids.add(s.id);need(typeof s.location==='string'&&s.location.trim().length>0,'source location required');}
 for(const f of [...m.sources,...m.derived]){need(typeof f.path==='string'&&f.path.length>0,'file path required');need(Number.isSafeInteger(f.size)&&f.size>0&&/^[a-f0-9]{64}$/.test(f.sha256),'actual size and SHA256 required');}
 for(const d of m.derived){need(Array.isArray(d.sources)&&d.sources.length>0&&d.sources.every(id=>ids.has(id)),'derived source links required');need(d.options&&typeof d.options==='object'&&!Array.isArray(d.options),'derived options required');need(Object.keys(m.tools).length>0,'derived tool versions required');}
 for(const v of Object.values(m.tools))need(typeof v==='string'&&v.trim().length>0,'invalid tool version');
}
let temp;
try{
 const [command,input,output,...rest]=process.argv.slice(2);need(input&&!rest.length&&['capture','verify'].includes(command),'usage: manifest.mjs capture specification.json manifest.json | verify manifest.json');
 const value=JSON.parse(readFileSync(input,'utf8')),base=dirname(resolve(input));
 if(command==='capture'){
  need(output,'capture output path required');const out=resolve(output);need(out!==resolve(input),'manifest must not overwrite specification');
  need(Array.isArray(value.sources)&&value.sources.length>0,'actual sources are required');need(Array.isArray(value.derived??[]),'invalid derived list');
  const record=f=>{need(typeof f.path==='string','path required');const path=realpathSync(resolve(base,f.path));need(path!==out,'manifest must not overwrite an asset');return {...f,path:relative(dirname(out),path),...digest(path)};};
  const tools={};for(const t of value.tools??[]){need(t.name&&t.command&&Array.isArray(t.args),'tools require name, command, args');const r=spawnSync(t.command,t.args,{encoding:'utf8',timeout:10000});need(r.status===0,'tool version command failed: '+t.name);tools[t.name]=(r.stdout+r.stderr).trim();}
  const manifest={schemaVersion:1,sources:value.sources.map(record),derived:(value.derived??[]).map(record),tools};validate(manifest);
  temp=out+'.'+randomUUID()+'.tmp';writeFileSync(temp,JSON.stringify(manifest,null,2)+'\n',{flag:'wx'});renameSync(temp,out);temp=undefined;console.log('captured '+manifest.sources.length+' sources and '+manifest.derived.length+' derived files');
 }else{
  need(!output,'verify accepts only a manifest path');validate(value);
  for(const f of [...value.sources,...value.derived]){const actual=digest(resolve(base,f.path));need(actual.size===f.size&&actual.sha256===f.sha256,'checksum/size mismatch: '+f.path);}
  console.log('verified '+value.sources.length+' sources and '+value.derived.length+' derived files');
 }
}catch(e){if(temp)try{unlinkSync(temp);}catch{}console.error('error: '+e.message);process.exitCode=1;}
