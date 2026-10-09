import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile, mkdir, rm, symlink, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { recover, validateCatalog } from '../published-assets.mjs';
import { DRUMS } from '../../../apps/drumrollworld/data.js';

const bytes = Buffer.from('actual recovery fixture bytes');
const asset = { path: '/images/artifact/1.jpg', url: 'https://drumroll.world/images/artifact/1.jpg', bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
const catalog = { schemaVersion: 1, assets: [asset] };
const response = (body) => new Response(body, { status: 200 });
test('committed catalog covers current original photos and every thumbnail link', async () => {
 const recorded = JSON.parse(await readFile(new URL('../../../docs/assets/drumrollworld-published-assets.json', import.meta.url), 'utf8'));
 validateCatalog(recorded);
 assert.equal(recorded.assets.length, 72);
 const originals = new Set(DRUMS.flatMap(entry => (entry.images || []).map(image => new URL(image.src, 'https://drumroll.world').pathname)));
 assert.deepEqual(new Set(recorded.assets.filter(a => a.kind === 'artifact-original').map(a => a.path)), originals);
 const expectedThumbs = new Set([...originals].map(path => path.replace(/\.(jpe?g|png)$/i, '.thumb.jpg')));
 assert.deepEqual(new Set(recorded.assets.filter(a => a.kind === 'artifact-thumbnail').map(a => a.path)), expectedThumbs);
 for (const item of recorded.assets.filter(a => a.kind === 'artifact-thumbnail')) assert.ok(originals.has(item.sourcePath));
 assert.equal(recorded.originalGlobeMasters.status, 'not-captured');
});
test('failed HTTP, network, stream and corrupt bodies preserve old files and clean temps', async () => {
 const root = await mkdtemp(join(tmpdir(), 'recovery-'));
 try {
  await mkdir(join(root, 'images/artifact'), { recursive: true });
  const target = join(root, 'images/artifact/1.jpg');
  const cases = [
   () => new Response('error', { status: 503 }),
   () => { throw new Error('network failed'); },
   () => response(Buffer.alloc(bytes.length + 1)),
   () => response(Buffer.alloc(bytes.length)),
   () => response(new ReadableStream({ start(controller) { controller.enqueue(bytes.subarray(0, 2)); controller.error(new Error('stream failed')); } })),
  ];
  for (const fetcher of cases) {
   await writeFile(target, 'original');
   await assert.rejects(recover(catalog, root, 'restore', fetcher));
   assert.equal(await readFile(target, 'utf8'), 'original');
   assert.deepEqual(await readdir(join(root, 'images/artifact')), ['1.jpg']);
  }
 } finally { await rm(root, { recursive: true, force: true }); }
});
test('recovery hashes actual streamed bytes and verify detects modified local assets', async () => {
 const root = await mkdtemp(join(tmpdir(), 'recovery-'));
 try {
  assert.equal(await recover(catalog, root, 'restore', () => response(bytes)), 1);
  assert.deepEqual(await readFile(join(root, 'images/artifact/1.jpg')), bytes);
  assert.equal(await recover(catalog, root, 'verify'), 1);
  await writeFile(join(root, 'images/artifact/1.jpg'), 'changed');
  await assert.rejects(recover(catalog, root, 'verify'), /checksum/);
  await assert.rejects(recover(catalog, root, 'restore', () => response('wrong')), /checksum/);
  assert.equal(await readFile(join(root, 'images/artifact/1.jpg'), 'utf8'), 'changed');
 } finally { await rm(root, { recursive: true, force: true }); }
});
test('catalog rejects traversal, duplicate paths, changed origins and invalid hashes', () => {
 for (const changed of [{ path: '/images/../secret' }, { path: '/images//artifact/1.jpg' }, { url: 'https://evil.test/image' }, { sha256: 'bogus' }]) assert.throws(() => validateCatalog({ ...catalog, assets: [{ ...asset, ...changed }] }));
 assert.throws(() => validateCatalog({ ...catalog, assets: [asset, asset] }));
});
test('recovery refuses symlink escape', async () => {
 const root = await mkdtemp(join(tmpdir(), 'recovery-'));
 const other = await mkdtemp(join(tmpdir(), 'recovery-outside-'));
 try {
  await mkdir(join(root, 'images'));
  await symlink(other, join(root, 'images/artifact'));
  await assert.rejects(recover(catalog, root, 'restore', () => response(bytes)), /symlink/);
 } finally { await rm(root, { recursive: true, force: true }); await rm(other, { recursive: true, force: true }); }
});
