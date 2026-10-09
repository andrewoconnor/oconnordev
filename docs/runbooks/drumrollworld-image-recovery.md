# DrumrollWorld image and texture recovery

Site deployment preserves `images/*`; that is not a backup or regeneration procedure.
This runbook separates byte-for-byte recovery of the published assets from regeneration
using original source masters. None of these commands uploads to S3.

## Recorded public assets

[`../assets/drumrollworld-published-assets.json`](../assets/drumrollworld-published-assets.json)
records all 72 app-referenced image URLs at its recorded repository revision:
27 original artifact photographs, their 27 thumbnails, 17 globe delivery textures/JPEGs,
and the favicon. Every entry includes an actual streamed SHA-256, byte size, observation
time, public URL, and mapped `s3://drumrollworld-web/images/...` key. Photo attribution
and licenses are retained from the app data. This is not a complete bucket inventory;
S3 version IDs were unavailable through public HTTP. Hashes are not S3 ETags.

Verify the live delivery bytes without saving them:

```sh
mise exec -- node scripts/drumrollworld/published-assets.mjs verify-remote \
  docs/assets/drumrollworld-published-assets.json
```

Restore the recorded assets locally and verify them again (about 166 MB):

```sh
mise exec -- node scripts/drumrollworld/published-assets.mjs restore \
  docs/assets/drumrollworld-published-assets.json /path/to/recovery
mise exec -- node scripts/drumrollworld/published-assets.mjs verify \
  docs/assets/drumrollworld-published-assets.json /path/to/recovery
```

The output contains `images/`, so configure generators with
`DRUMROLLWORLD_IMAGES_DIR=/path/to/recovery/images`. Downloads are streamed, checked
against the committed catalog, and atomically replaced only after verification.
Missing/changed remote assets fail; existing local bytes survive failed downloads.
Do not refresh the hashes merely to make an unexpected change pass verification.
Keep a separate verified copy: public URLs alone do not protect against bucket loss.
Use a **trusted, exclusively controlled local recovery directory** (for example,
created with `mkdir -m 700`), with no other process modifying its directory tree while
recovery runs. Existing symlinks and traversal paths are rejected, but pathname checks
are not race-resistant against concurrent directory/symlink replacement. This is not a
filesystem sandbox for attacker-controlled output paths. Replacement is atomic **per
asset**, not transactional across the entire catalog; a later failure leaves earlier
verified assets restored.

## Original globe masters: outstanding source inventory

The owner reports original masters on a laptop and in S3. Their exact paths/keys and
original checksums have **not** been supplied or verified. Required files:

- `earthmap.jpg`: full-resolution color master.
- `earthheight.jpg`: grayscale elevation master for Sobel normals.
- `earthspec.jpg`: original specular mask.
- `stars.jpg`: original star-field master.

The published KTX2/JPEG files are derived delivery assets. Their recorded hashes permit
exact restoration, but cannot reconstruct the original elevation/master files or prove
a rebuilt normal map matches the old encoder. Do not rename delivery images as masters.
Capture those four actual originals and their laptop/S3 locations before rebuilding.

Default input is `apps/drumrollworld/textures/src`; default output is
`apps/drumrollworld/images/globe`. Both are anchored to the repository, not the caller's
working directory. External paths are recommended for disaster recovery:

```sh
DRUMROLLWORLD_TEXTURE_SOURCE_DIR=/path/to/original-masters \
DRUMROLLWORLD_IMAGES_DIR=/path/to/regenerated/images \
FORCE=1 mise exec -- bash scripts/drumrollworld/build-globe-textures.sh
```

Prerequisites are ImageMagick 7 (`magick`), KTX-Software 4 (`ktx`), and pinned Node
(`mise exec`). Sources, helper, options and decodable headers are checked before creating
output/temp artifacts. On this Hermes instance, verified ImageMagick 7.1.2-32 and KTX
4.4.2 are installed persistently; expose them with:

```sh
export PATH=/opt/data/tools/drumrollworld:/opt/data/tools/drumrollworld/KTX-Software-4.4.2-Linux-x86_64/bin:$PATH
```

Source/output directories must not overlap. The restored helper
at `scripts/drumrollworld/lib/height-to-normal.mjs` uses a horizontally wrapping Sobel
filter and vertically clamped bounds; `--flip-y` reverses the normal green channel.
Masters remain read-only. Generated files are staged before replacement.

Use `FORCE=1` after changing tools or settings: mtime skipping is an optimization, not
proof of reproducibility. Record every nondefault environment option (TIERS,
STARS_TIERS, NORMAL_MAX_WIDTH, NORMAL_STRENGTH, NORMAL_PREBLUR, SHARPEN,
SHARPEN_STARS, JPEG_QUALITY, UASTC_QUALITY, ZSTD_LEVEL, FALLBACK_WIDTH,
STARS_FALLBACK_WIDTH). The defaults remain in the generator. Rebuilding with the
restored helper is not a claim of byte equality with historical outputs.

## Regenerate artifact thumbnails

Original artifact photographs are available in the published catalog, so they can be
restored and then used as thumbnail sources. Keep outputs separate for comparison:

```sh
DRUMROLLWORLD_IMAGES_DIR=/path/to/recovery/images \
DRUMROLLWORLD_THUMBS_OUTPUT_DIR=/path/to/regenerated/images \
FORCE=1 mise exec -- bash scripts/drumrollworld/build-thumbs.sh
```

ImageMagick 7 and Node are required. Discovery errors fail rather than silently
reporting an empty success. Existing thumbnails and `globe/` are excluded. Originals
are never overwritten. Compare generated thumbnail hashes to the catalog if exact
historical bytes are required; different ImageMagick versions may yield different bytes.

## Capture original/derived provenance

Write a specification alongside your local masters and generated outputs. Paths resolve
relative to that specification, not the shell's current directory. Supply all four globe
sources and all generated outputs in a real recovery inventory. This short example
illustrates one link; it is not a complete manifest:

```json
{
  "sources": [
    {"id": "height", "path": "masters/earthheight.jpg", "location": "s3://YOUR-BUCKET/EXACT-ORIGINAL-KEY"}
  ],
  "derived": [
    {"path": "images/globe/earthnormal2k.ktx2", "sources": ["height"], "options": {"NORMAL_STRENGTH": "4.0", "NORMAL_PREBLUR": "0x0.5", "FORCE": "1"}}
  ],
  "tools": [
    {"name": "node", "command": "node", "args": ["--version"]},
    {"name": "magick", "command": "magick", "args": ["--version"]},
    {"name": "ktx", "command": "ktx", "args": ["--version"]}
  ]
}
```

```sh
mise exec -- node scripts/drumrollworld/manifest.mjs capture \
  /path/to/specification.json /path/to/manifest.json
mise exec -- node scripts/drumrollworld/manifest.mjs verify /path/to/manifest.json
```

Capture reads real bytes and tool-version output; it never fills in guessed checksums.
Verification rejects missing, empty or modified sources/outputs. Locations are owner-
supplied provenance labels, not independently authenticated S3 queries. Retain the
manifest with the originals and re-capture only after a deliberate change/rebuild.

## Runtime degradation and tests

The searchable list is rendered/selected before WebGL construction or texture awaits.
WebGL initialization failures show `#globeUnavailable[role=status]`; list, navigation,
and gallery stay functional. The loading overlay has a 20-second watchdog and a
1-second removal fallback; stalled texture requests do not block artifact browsing,
although the requests themselves are not aborted. Tier completion rechecks the applied
rank, disposes discarded textures and updates the star cache only for applied textures.

```sh
mise run build:drumrollworld
mise run test:drumrollworld
```

Runtime tests execute shipped `main.js` with controlled DOM/WebGL/network dependencies.
Pipeline tests include real tiny-fixture ImageMagick/KTX integration when those tools
are available, and explicitly skip those two integrations otherwise. Node-only guards,
normal-map math, provenance and published recovery tests always run. CI runs them
before AWS authentication; no test uploads generated assets.
