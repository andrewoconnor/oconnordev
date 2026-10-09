import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, existsSync, readFileSync, rmSync, symlinkSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const scripts=new URL('../',import.meta.url).pathname;
function sandbox(fn){const dir=mkdtempSync(join(tmpdir(),'pipeline-test-'));try{fn(dir);}finally{rmSync(dir,{recursive:true,force:true});}}
function mocks(dir){const bin=join(dir,'bin');mkdirSync(bin);for(const cmd of ['magick','ktx'])writeFileSync(join(bin,cmd),'#!/bin/sh\nexit 0\n',{mode:0o755});return `${bin}:${process.env.PATH}`;}
function run(script,env){return spawnSync('bash',[join(scripts,script)],{env:{...process.env,...env},encoding:'utf8'});}
test('globe rejects absent masters before output creation (mock dispatch only)',()=>sandbox(dir=>{
 const out=join(dir,'out'); const r=run('build-globe-textures.sh',{PATH:mocks(dir),DRUMROLLWORLD_TEXTURE_SOURCE_DIR:join(dir,'missing'),DRUMROLLWORLD_IMAGES_DIR:out});assert.notEqual(r.status,0);assert.equal(existsSync(out),false);
}));
test('invalid numeric settings fail before output creation (mock dispatch only)',()=>sandbox(dir=>{
 const out=join(dir,'out'),src=join(dir,'src');mkdirSync(src);for(const f of ['earthmap','earthheight','earthspec','stars'])writeFileSync(join(src,f+'.jpg'),'guard fixture, not an image');
 const path=mocks(dir);
 for(const settings of [{TIERS:'bogus'},{TIERS:'08'},{NORMAL_STRENGTH:'-1'},{JPEG_QUALITY:'101'},{UASTC_QUALITY:'5'},{ZSTD_LEVEL:'23'},{NORMAL_MAX_WIDTH:'NaN'},{SHARPEN:'invalid'},{NORMAL_PREBLUR:'invalid'}]){
 const r=run('build-globe-textures.sh',{PATH:path,...settings,DRUMROLLWORLD_TEXTURE_SOURCE_DIR:src,DRUMROLLWORLD_IMAGES_DIR:out});assert.notEqual(r.status,0);assert.match(r.stderr,/invalid/);assert.equal(existsSync(out),false);
 }
}));
test('missing helper is rejected before output creation',()=>sandbox(dir=>{
 const tree=join(dir,'repo','scripts','drumrollworld');mkdirSync(tree,{recursive:true});writeFileSync(join(tree,'build.sh'),readFileSync(join(scripts,'build-globe-textures.sh')));
 const out=join(dir,'out'),src=join(dir,'src');mkdirSync(src);for(const f of ['earthmap','earthheight','earthspec','stars'])writeFileSync(join(src,f+'.jpg'),'guard fixture');
 const r=spawnSync('bash',[join(tree,'build.sh')],{env:{...process.env,PATH:mocks(dir),DRUMROLLWORLD_TEXTURE_SOURCE_DIR:src,DRUMROLLWORLD_IMAGES_DIR:out},encoding:'utf8'});
 assert.notEqual(r.status,0);assert.match(r.stderr,/helper/);assert.equal(existsSync(out),false);
}));
test('missing command is rejected before output creation',()=>sandbox(dir=>{
 const bin=join(dir,'bin');mkdirSync(bin);writeFileSync(join(bin,'dirname'),'#!/bin/sh\nprintf "%s\\n" "'+scripts+'"\n',{mode:0o755});
 const out=join(dir,'out');const r=spawnSync('/bin/bash',[join(scripts,'build-globe-textures.sh')],{env:{...process.env,PATH:bin,DRUMROLLWORLD_IMAGES_DIR:out},encoding:'utf8'});assert.notEqual(r.status,0);assert.match(r.stderr,/magick.*not found/);assert.equal(existsSync(out),false);
}));
test('thumbnail discovery failure is not reported as empty success',()=>sandbox(dir=>{
 const path=mocks(dir);writeFileSync(join(dir,'bin','find'),'#!/bin/sh\nexit 7\n',{mode:0o755});const r=run('build-thumbs.sh',{PATH:path,DRUMROLLWORLD_IMAGES_DIR:dir});assert.notEqual(r.status,0);
}));
const available=cmd=>spawnSync(cmd,['--version']).status===0;
test('real thumbnail handles trailing slash and unusual filenames',{skip:!available('magick')},()=>sandbox(dir=>{
 const src=join(dir,'src'),out=join(dir,'out');mkdirSync(src);
 const name='space [1]\nimage.png';assert.equal(spawnSync('magick',['-size','16x8','gradient:',join(src,name)]).status,0);
 const before=readFileSync(join(src,name));const r=run('build-thumbs.sh',{DRUMROLLWORLD_IMAGES_DIR:src+'/',DRUMROLLWORLD_THUMBS_OUTPUT_DIR:out});
 assert.equal(r.status,0,r.stderr);assert.ok(existsSync(join(out,'space [1]\nimage.thumb.jpg')));assert.deepEqual(readFileSync(join(src,name)),before);
}));
test('real ImageMagick thumbnail excludes globe/thumbs and preserves input',{skip:!available('magick')},()=>sandbox(dir=>{
 const src=join(dir,'src'),out=join(dir,'out');mkdirSync(join(src,'globe'),{recursive:true});
 const ppm='P3\n2 2\n255\n255 0 0 0 255 0 0 0 255 255 255 255\n';writeFileSync(join(dir,'fixture.ppm'),ppm);
 for(const f of ['image.png','old.thumb.jpg','globe/earth.jpg'])assert.equal(spawnSync('magick',[join(dir,'fixture.ppm'),join(src,f)]).status,0);
 const before=readFileSync(join(src,'image.png'));const r=run('build-thumbs.sh',{DRUMROLLWORLD_IMAGES_DIR:src,DRUMROLLWORLD_THUMBS_OUTPUT_DIR:out});assert.equal(r.status,0,r.stderr);assert.ok(existsSync(join(out,'image.thumb.jpg')));assert.equal(existsSync(join(out,'old.thumb.thumb.jpg')),false);assert.equal(existsSync(join(out,'globe')),false);assert.deepEqual(readFileSync(join(src,'image.png')),before);
}));
test('real globe rejects output aliases inside the master directory',{skip:!available('magick')||!available('ktx')},()=>sandbox(dir=>{
 const src=join(dir,'src'),alias=join(dir,'alias');mkdirSync(src);symlinkSync(src,alias);
 for(const f of ['earthmap','earthheight','earthspec','stars'])assert.equal(spawnSync('magick',['-size','16x8','gradient:',join(src,f+'.jpg')]).status,0);
 const r=run('build-globe-textures.sh',{DRUMROLLWORLD_TEXTURE_SOURCE_DIR:src,DRUMROLLWORLD_IMAGES_DIR:alias,TIERS:'16',STARS_TIERS:'16',FALLBACK_WIDTH:'16',STARS_FALLBACK_WIDTH:'16'});
 assert.notEqual(r.status,0);assert.match(r.stderr,/must not overlap/);assert.equal(existsSync(join(src,'globe')),false);
}));
test('real ImageMagick/KTX tiny mip chain validates',{skip:!available('magick')||!available('ktx')},()=>sandbox(dir=>{
 const src=join(dir,'src'),out=join(dir,'out');mkdirSync(src);for(const f of ['earthmap','earthheight','earthspec','stars'])assert.equal(spawnSync('magick',['-size','16x8','gradient:',join(src,f+'.jpg')]).status,0);
 const r=run('build-globe-textures.sh',{DRUMROLLWORLD_TEXTURE_SOURCE_DIR:src,DRUMROLLWORLD_IMAGES_DIR:out,TIERS:'16',STARS_TIERS:'16',FALLBACK_WIDTH:'16',STARS_FALLBACK_WIDTH:'16'});assert.equal(r.status,0,r.stderr);
 for(const f of ['earthmap16px','earthnormal16px','earthspec16px','stars16px']){const v=spawnSync('ktx',['validate',join(out,'globe',f+'.ktx2')]);assert.equal(v.status,0,v.stderr.toString());}
}));
