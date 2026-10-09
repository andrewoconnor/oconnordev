#!/usr/bin/env node
import { readFileSync, writeFileSync, renameSync, unlinkSync, realpathSync } from 'node:fs';
import { resolve, dirname, basename } from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';

// Sobel derivatives use +x right and +y down. --flip-y negates the
// resulting green component (not the row order), for top-down JPEG upload.
export function heightToNormal(data, width, height, strength, flipY = false) {
  if (!Number.isSafeInteger(width) || width < 1 || !Number.isSafeInteger(height) || height < 1 || !Number.isSafeInteger(width * height * 3)) throw new Error('dimensions must be positive safe integers');
  if (!Number.isFinite(strength) || strength < 0) throw new Error('strength must be finite and nonnegative');
  if (!(data instanceof Uint8Array) || data.length !== width * height) throw new Error('height input must contain exactly width * height bytes');
  const out = Buffer.alloc(width * height * 3);
  const sample = (x,y) => data[Math.max(0,Math.min(height-1,y))*width + ((x+width)%width)] / 255;
  for(let y=0;y<height;y++) for(let x=0;x<width;x++) {
    const dx=(sample(x+1,y-1)+2*sample(x+1,y)+sample(x+1,y+1)-sample(x-1,y-1)-2*sample(x-1,y)-sample(x-1,y+1))/8;
    const dy=(sample(x-1,y+1)+2*sample(x,y+1)+sample(x+1,y+1)-sample(x-1,y-1)-2*sample(x,y-1)-sample(x+1,y-1))/8;
    const nx=-dx*strength, ny=-dy*strength*(flipY?-1:1), length=Math.hypot(nx,ny,1), i=(y*width+x)*3;
    out[i]=Math.round((nx/length+1)*127.5); out[i+1]=Math.round((ny/length+1)*127.5); out[i+2]=Math.round((1/length+1)*127.5);
  }
  return out;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  let temp;
  try {
    const [w,h,s,input,output,...flags]=process.argv.slice(2);
    if (!output || flags.some(f=>f!=='--flip-y') || flags.length>1) throw new Error('usage: height-to-normal.mjs width height strength input.gray output.rgb [--flip-y]');
    const target=resolve(realpathSync(dirname(resolve(output))),basename(output));
    if(resolve(input)===resolve(output) || realpathSync(input)===target) throw new Error('input and output must differ');
    const result=heightToNormal(readFileSync(input),Number(w),Number(h),Number(s),flags.includes('--flip-y'));
    temp=`${output}.${randomUUID()}.tmp`;
    writeFileSync(temp,result,{flag:'wx'}); renameSync(temp,output); temp=undefined;
  } catch(error) { if(temp) {try{unlinkSync(temp);}catch{}} console.error(`error: ${error.message}`); process.exitCode=1; }
}
