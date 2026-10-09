#!/usr/bin/env node
// Recover recorded delivery bytes, never claim derived textures are source masters.
import { createHash, randomUUID } from 'node:crypto';
import { createReadStream, createWriteStream } from 'node:fs';
import { lstat, mkdir, readFile, rename, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { pathToFileURL } from 'node:url';

export function validateCatalog(catalog) {
 if (catalog.schemaVersion !== 1 || !Array.isArray(catalog.assets) || !catalog.assets.length) throw new Error('invalid catalog');
 const paths = new Set();
 for (const asset of catalog.assets) {
  if (!/^\/images\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+$/.test(asset.path) || asset.path.split('/').some(p => p === '.' || p === '..') || paths.has(asset.path)) throw new Error('invalid/duplicate asset path');
  if (asset.url !== `https://drumroll.world${asset.path}` || !Number.isSafeInteger(asset.bytes) || asset.bytes <= 0 || !/^[a-f0-9]{64}$/.test(asset.sha256)) throw new Error('invalid asset URL/checksum');
  paths.add(asset.path);
 }
}
async function safeTarget(root, assetPath, create) {
 // Reject existing symlinks. Caller must exclusively control the tree during recovery:
 // pathname checks do not confine writes against concurrent directory replacement.
 const target = join(root, assetPath.slice(1));
 const components = resolve(target).split('/').filter(Boolean);
 let current = '/';
 for (const [index, component] of components.entries()) {
  current = join(current, component);
  let stat;
  try { stat = await lstat(current); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (stat?.isSymbolicLink()) throw new Error('symlink path refused: ' + current);
  if (index < components.length - 1) {
   if (stat && !stat.isDirectory()) throw new Error('not a directory: ' + current);
   if (!stat && create) await mkdir(current);
  }
 }
 return target;
}
async function hashStream(stream, asset, destination) {
 const digest = createHash('sha256'); let size = 0;
 const counter = new Transform({ transform(chunk, _encoding, callback) {
  size += chunk.length;
  if (size > asset.bytes) return callback(new Error('checksum size exceeded: ' + asset.path));
  digest.update(chunk); callback(null, chunk);
 } });
 if (destination) await pipeline(stream, counter, createWriteStream(destination, { flags: 'wx' }));
 else { stream.pipe(counter); stream.on('error', error => counter.destroy(error)); for await (const _chunk of counter) { /* consume */ } }
 if (size !== asset.bytes || digest.digest('hex') !== asset.sha256) throw new Error('checksum mismatch: ' + asset.path);
}
export async function recover(catalog, root, mode, fetcher = fetch) {
 validateCatalog(catalog);
 if (!['restore', 'verify', 'verify-remote'].includes(mode)) throw new Error('unknown mode');
 let count = 0;
 for (const asset of catalog.assets) {
  if (mode === 'verify-remote') {
   const response = await fetcher(asset.url, { signal: AbortSignal.timeout(120000), redirect: 'error', headers: { 'Accept-Encoding': 'identity' } });
   if (!response.ok || !response.body) throw new Error('HTTP failure: ' + asset.url);
   await hashStream(Readable.fromWeb(response.body), asset);
  } else {
   const target = await safeTarget(resolve(root), asset.path, mode === 'restore');
   if (mode === 'verify') await hashStream(createReadStream(target), asset);
   else {
    const temporary = target + '.' + randomUUID() + '.tmp';
    try {
     const response = await fetcher(asset.url, { signal: AbortSignal.timeout(120000), redirect: 'error', headers: { 'Accept-Encoding': 'identity' } });
     if (!response.ok || !response.body) throw new Error('HTTP failure: ' + asset.url);
     await hashStream(Readable.fromWeb(response.body), asset, temporary);
     // Preserve existing files on network/checksum failures; atomically replace only verified bytes.
     await safeTarget(resolve(root), asset.path, false);
     await rename(temporary, target);
    } finally { await rm(temporary, { force: true }); }
   }
  }
  count++;
 }
 return count;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
 try {
  const [mode, catalogFile, outputRoot, ...extra] = process.argv.slice(2);
  if (!catalogFile || extra.length || (mode !== 'verify-remote' && !outputRoot)) throw new Error('usage: published-assets.mjs verify-remote catalog.json | restore|verify catalog.json output-root');
  const catalog = JSON.parse(await readFile(catalogFile, 'utf8'));
  console.log(`${mode}: ${await recover(catalog, outputRoot || '.', mode)} recorded assets verified`);
 } catch (error) { console.error('error: ' + error.message); process.exitCode = 1; }
}
