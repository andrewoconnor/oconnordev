# DrumrollWorld production deployment

## Scope

`apps/drumrollworld/` is a static browser app with a reproducible npm/esbuild
build. Three.js, Globe.gl and the matching KTX2 decoder are self-hosted rather
than fetched from runtime CDNs. Its existing private bucket and
CloudFront distribution belong to the `drumrollworld` Spacelift stack, rooted
at `infra/aws/drumrollworld`, in the PRODUCTION account (`767397796791`). This
pipeline does not replace those resources or move them into the `production`
state. It creates a deployment identity and configuration, not another hosting
service or a new fixed-monthly-cost stack.

The workflow `.github/workflows/drumrollworld-site.yml` checks pull requests
with Biome, installs the exact npm lock without dependency lifecycle scripts,
builds and tests the publish directory. Only a `master` push or manual dispatch
on `master` can deploy.
The check job has no OIDC permission; the deploy job obtains short-lived
credentials through the existing chain:

1. GitHub OIDC -> `oconnordev-github-actions-broker` in TOOLS.
2. TOOLS broker -> `drumrollworld-site-deploy` in PRODUCTION.

The broker still admits only the exact repository's `master` OIDC subject
and `sts.amazonaws.com` audience. It can assume only the existing OConnorDev
site role and the new DrumrollWorld site role. The new role trusts only that
broker and can list/sync only `drumrollworld-web` and invalidate only its
specific CloudFront distribution. No AWS access keys are stored in GitHub.

Deployments are serialized without interrupting an active S3 sync. A queued
deploy checks out current `master`, not an older push's snapshot, then reruns
format, lint, build and release tests before obtaining credentials. This
prevents a queued older push from restoring stale application code. An update merged during a running
deployment is handled by the next queued run. S3 uploads are not an atomic
release switch, and CloudFront invalidation propagation is asynchronous.

## Images and globe textures are outside this checkout

The initial app commit contains only `index.html`, `styles.css`, `main.js` and
`data.js`. It references `images/` for its favicon, entry photos and KTX2/globe
texture tiers. Those assets are not reproducible from this repository today.
Read-only HTTP checks during implementation found the live homepage, favicon,
first-paint earth texture and a representative entry photo returning HTTP 200.
This confirms those samples, not an inventory or backup of every asset.

The workflow excludes `images/*` and prior `assets/*` from root sync/deletion.
See `.github/workflows/drumrollworld-site.yml` for the complete publication
commands, including cache metadata, the diagnostic exclusion and the narrowly
scoped KTX2 metadata repair described below.

AWS CLI excludes matching destination objects from deletion. The deploy role
also explicitly denies `s3:DeleteObject` on `drumrollworld-web/images/*`, so a
future accidental removal of the exclusion cannot delete existing images.
Root code objects removed from the release are still deleted. Runtime assets
are uploaded first without deletion, then excluded from the root sync. Older
hashed modules and versioned decoder assets remain available while cached HTML
and open clients still reference them. This is not an atomic release switch;
asset cleanup needs a separate reviewed retention procedure, not an unbounded
`--delete` during publication. The workflow does
not upload image bytes from the checkout. It now manages only the content-type
and cache metadata of existing `images/globe/*.ktx2` via server-side self-copy;
other images remain untouched. Asset publication needs a separate explicit
procedure or a future versioned asset-source design. Do not remove the exclusion without migrating that asset
ownership. The original fallback picture is now a repository-owned SVG outside
`images/`; it is included in the release.

## Self-hosted runtime dependencies

Exact direct versions are recorded in `apps/drumrollworld/package.json`:
Three.js `0.186.1`, Globe.gl `2.46.2`, and build-only esbuild `0.28.2`.
`package-lock.json` fixes transitive versions and integrity hashes. Node
`26.11.1` is pinned and checksummed in the repository mise lock.

```sh
mise run build:drumrollworld
mise run test:drumrollworld
```

The build task runs `npm ci --ignore-scripts --no-audit --no-fund` before the
explicit application build. Dependency lifecycle scripts are not executed.
The publish directory is `apps/drumrollworld/dist/`, never `node_modules/` or
the source checkout. JavaScript is bundled for the browser with one shared
Three.js; content-hashed module assets and the exact matching decoder JS/WASM
are served by the existing CloudFront origin. No import map or CDN dependency
preload is required. Third-party attribution is published with the site.
Build output and installed packages are ignored by Git and source Biome checks;
release-specific Node tests check the generated artifacts.

To update, select compatible exact package versions, regenerate the npm lock,
update the local decoder path/preloads to match Three.js, then rebuild, test,
and browser-check with external CDN traffic blocked. Commit sources and locks,
not generated bundles or installed packages. Package downloads happen during
CI only; browser startup no longer depends on esm.sh or unpkg.com. Image/texture
asset ownership and the existing S3/CloudFront infrastructure are unchanged.
After the original deployment bootstrap, the dependency migration itself needed
no new Terraform resources, IAM permissions or infrastructure apply: the existing
workflow builds, syncs and invalidates CloudFront on `master`.

The background-texture/cache-metadata update below additionally requires the
narrow KTX2 read grant to be applied before the new deployment workflow runs.

## Background texture upgrades

Once the four first-paint KTX2 textures have completed and the 2k tier is
installed, the app schedules 4k, 8k and (when supported) 10k upgrades during idle
time (`requestIdleCallback` with a 3-second timeout, or a 500ms timer fallback).
No zoom is needed. Each tier is installed rather than retained as a prefetch
cache; superseded map/normal/specular textures are disposed. Stars are reused
while their resolution stays unchanged. The normal map still stops at 8k.

A single automatic upgrade owns at most four texture requests. A zoom request
starts immediately if no tier is loading, or takes the next slot after the
current tier drains; it can skip intermediate background tiers. Failure does
not open another slot until late outstanding requests settle and their textures
are disposed. A stalled request therefore stops background progress rather than
accumulating more requests or GPU allocations. Each automatic tier is attempted
once per page lifetime, avoiding retries on auto-rotation change events. Reload
to retry a missing higher tier. Already-installed textures remain visible.

The GPU ceiling and existing phone-sized 8k ceiling apply to background and zoom
loads; they are rechecked before installation if the viewport changes in flight.
Save-Data and 2g connections stay at 2k. JPEG fallback stays at its existing 2k
tier and does not schedule further compressed loads. Loading-screen watchdog,
list/search/navigation and the wasm-only no-JavaScript-eval CSP are unchanged.
This deliberately increases background bandwidth on non-data-saving devices;
it is not a prediction of production texture download time or mobile GPU usage.

## Cache metadata, KTX2 MIME and private build diagnostics

Only esbuild's generated `assets/main-XXXXXXXX.js` entry (eight uppercase
alphanumeric hash characters) receives
`Cache-Control: public,max-age=31536000,immutable`. The build owns that namespace
and derives the filename from bundle content. Do not overwrite an old hashed
entry with different bytes or introduce a stable file matching that namespace.
Older bundles are preserved. The linked `.LEGAL.txt` file is not assumed to have
an independent content hash.

HTML, CSS, notices, manifests and other mutable site files use
`public,max-age=0,must-revalidate`. All stable runtime assets, including
`assets/question-image.svg` and the `basis-1.50.0-no-eval` JS/WASM paths, also
revalidate. A release/version label is **not** a content-address guarantee; those
paths could be repaired in place. Globe textures such as `earthmap8k.ktx2` are
stable mutable URLs, not immutable assets. Query-string cache busting is not a
solution with this distribution's query-string forwarding disabled. A future
immutable texture cache requires content-addressed URLs and application changes.

The workflow uploads assets before HTML, preserving prior runtime assets and
all images. Explicit `s3 cp` passes also update metadata on unchanged files:
`sync --cache-control` alone skips them. This causes repeat uploads/object
versions and request/storage costs; it is deliberate rather than a claim that
sync retroactively repairs headers. The existing CloudFront maximum TTL remains
86400 seconds, so the year-long header is a browser directive, not a promise of
a year in CloudFront. The zero minimum TTL permits mutable responses to
revalidate. The existing `/*` invalidation clears prior edge metadata after
publication; it cannot recall responses already cached in a browser.

`build-meta.json` remains in the local build output for dependency graph,
license and reproducibility tests. Both root publication passes exclude it.
Because exclusions also protect destination objects from `sync --delete`, the
production-only deployment explicitly removes **only**
`s3://drumrollworld-web/build-meta.json` before invalidation. PR checks never
obtain AWS credentials or perform this removal. S3 version history may retain
prior copies privately; this is not a purge of historical versions.

Existing `images/globe/*.ktx2` receive explicit `Content-Type: image/ktx2` and
revalidation headers via a scoped S3-to-S3 self-copy, not unreliable filename
inference. Bytes are copied server-side without downloading or regenerating
artwork, and no images are deleted. `--metadata-directive REPLACE` intentionally
replaces user metadata and unspecified content headers on these KTX2 objects;
check for any custom metadata/content-encoding requirements before rollout.
Other photo/JPEG/thumbnail objects are not included. Each deployment creates new
versions of the selected objects in the versioned bucket.

**Rollout prerequisite:** self-copy requires `s3:GetObject`, which the old deploy
role did not have. Review and manually apply the `drumrollworld` stack's single
new read grant, limited to `drumrollworld-web/images/globe/*.ktx2`, before running
the updated workflow. Existing writes, image-delete denial, role trust and
CloudFront permissions are unchanged. Repair runs before application uploads;
without this apply the workflow fails before publishing new code, and the
invalidation will not run. Metadata repair itself is not an atomic transaction.
There were no live IAM/S3/CloudFront changes during local verification.

After deployment and invalidation completion, check the current hashed module,
`/`, `/styles.css`, the decoder JS/WASM, an existing KTX2 URL, and
`/build-meta.json`: expect immutable only on the module, revalidation on stable
objects, `image/ktx2` on the KTX2, and a genuine 404 for the diagnostic. Review
headers/body from an allowed country; local tests are not deployed evidence.
Rollback by reverting the application/workflow and redeploying current master;
review and manually revert the read grant separately if no repair is needed.
Do not mark stable texture/decoder URLs immutable during rollback.

### Opt-in browser regression without installing dependencies

After building the release with existing dependencies, run:

```sh
KTX2_FIXTURE=/path/to/genuine.ktx2 JPEG_FIXTURE=/path/to/image.jpg \
CHROMIUM=/path/to/pinned/chrome-headless-shell \
node scripts/drumrollworld/test/background-browser.cjs
```

`PLAYWRIGHT_MODULE` can select an existing installation; `BROWSER_SCREENSHOT`
can save the desktop render. This test holds an initial normal request open to
prove higher tiers cannot start early, holds background 4k requests while real
mouse-wheel zoom queues 10k, and requires exact completed worker transcodes:
desktop 14, phone 11, Save-Data 4, JPEG fallback 0 and prioritized zoom 11. All
modes require peak KTX2 request concurrency <=4, zero page errors and zero
compatibility CSP violations. Desktop/zoom emulate a 16384 capability to exercise
the 10k scheduling path on SwiftShader; the fixture dimensions stay tiny, so
this does **not** prove production 10k memory/performance. The existing security
browser regression also retains exact hardware-dependent transcode counts and
its explicit no-eval/foreign-script attacks.

The prior synthetic pipeline fixtures were not present in this instance.
Local verification reused genuine upstream Three r186 encoded fixtures, fetched
read-only, not fabricated KTX2 headers or production artwork:

- `https://raw.githubusercontent.com/mrdoob/three.js/r186/examples/textures/ktx2/2d_uastc.ktx2`
  SHA256 `21b6912cae1f074ae3eda1b751f43c36eafc7eb83f3af71f85bba2ccbafce125`
- `https://raw.githubusercontent.com/mrdoob/three.js/r186/examples/textures/uv_grid_opengl.jpg`
  SHA256 `909d9a1eb2a5d5de9d221a5e8de4e9119d409decddf522d48896bd51523d354d`

No compiler, package installation, dependency version/lockfile change or edit to
installed package contents was needed. A node_modules directory symlink changes
esbuild's resolved metafile paths and is rejected by the existing single-Three
validator; an unchanged copy of the existing dependencies avoids relaxing that
assertion.

## Compression and real 404 rollout

This change enables `compress = true` on the existing distribution. It retains
legacy `forwarded_values`, no query strings/cookies/headers, and the existing
0/3600/86400-second minimum/default/maximum TTLs. This supports CloudFront gzip
for eligible responses; Brotli is **not promised** with legacy forwarding. There
is no cache-policy migration or new infrastructure service.

Both origin 403 and 404 map to `/404.html` with viewer status **404**, never 200
or the application shell. Private S3 without `s3:ListBucket` for CloudFront
commonly returns 403 for absent keys. The explicit 404 mapping also handles an
origin that returns 404. The configured error minimum TTL is 10 seconds (S3 has
a one-second floor even if configured to zero); origin cache headers can extend
error caching. This is deliberately short, not a zero-cache guarantee.

**Tradeoff:** the 403 mapping also masks genuine origin permission denials as
404. If known-good objects start returning 404, investigate the bucket policy,
OAC and object existence rather than assuming every response means a missing
key. It does not grant any new access: private S3, public-access blocks,
distribution-scoped OAC read permission, TLS enforcement, security headers and
US/CA/GB/DE geographic restrictions remain unchanged. Do not add ListBucket,
public reads or relax restrictions to obtain a prettier error page.

Roll out in this order (the user owns publication and infrastructure apply):

1. Merge the reviewed site change and complete the existing **drumrollworld
   site** workflow on current `master` **before applying CloudFront changes**.
   `build.js` copies the standalone, JS-free page byte-for-byte into
   `dist/404.html`; the existing root sync automatically publishes it with HTML
   content type. Asset-first upload, `images/*`/`assets/*` preservation,
   pre-authentication validation and credential boundaries do not change.
   Verify `https://drumroll.world/404.html` returns 200 and `text/html` with the
   expected page. This direct object request is 200; missing URLs must be 404.
2. Review the actual `drumrollworld` Spacelift stack plan, then manually apply
   the compression and both error mappings. A speculative plan or these offline
   mock-provider tests prove intended configuration, **not** deployed behavior.
3. After distribution deployment completes, manually dispatch the existing site
   workflow on `master` again. Its `/*` invalidation clears previously cached
   uncompressed bundles and error responses as well as the HTML; wait for that
   invalidation to complete. This is not an atomic rollout.
4. From an allowed country, use the current hashed JS path from the published
   homepage, not a guessed historical filename:

   ```sh
   curl -sS -D - -o /dev/null -H 'Accept-Encoding: gzip' 'https://drumroll.world/assets/main-CURRENT.js'
   curl -sS -D - -o /dev/null 'https://drumroll.world/a-new-deliberately-missing-path'
   ```

   Expect the eligible JS response to be 200 with `Content-Encoding: gzip`.
   Expect the new missing URL to be **404** with `Content-Type: text/html`;
   inspect its body for the standalone error page, not S3 XML or the globe app.
   Also verify homepage, security headers and existing images/decoder assets.
   Geographic denials are not missing-object tests. If compression is absent,
   check deployment/invalidation completion and response eligibility before
   changing TTLs or policies.

Pre-change public HTTP evidence supplied during this review: `/robots.txt`
returned 403 with `application/xml`; an actual GET of
`/assets/main-OVHBM2AQ.js` requesting gzip returned 200, 2,062,917 bytes and no
`Content-Encoding`. Local gzip of that bundle was 591,033 bytes (71.35% smaller).
That is a **local estimate**, not a measured CloudFront saving or a guarantee
of 70% reduction for this or every object. Public HTTP does not establish live
CloudFront configuration. Post-apply header/body checks are still required.

Offline workload verification (reuse the persistent provider cache):

```sh
export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-$HOME/.opentofu.d/plugin-cache}"
mkdir -p "$TF_PLUGIN_CACHE_DIR"
mise exec -- tofu -chdir=infra/aws/drumrollworld init -backend=false -input=false -no-color -lockfile=readonly
mise exec -- tofu -chdir=infra/aws/drumrollworld test -no-color
```

For rollback, revert the reviewed CloudFront settings and manually apply the
`drumrollworld` stack, then use the same workflow invalidation. Retain the
harmless `/404.html` object until the old mappings have stopped serving; do not
remove it first and strand an active custom-error mapping.

## First rollout: merge is not sufficient

Infrastructure stacks retain their existing manual-apply policy. After merging:

1. Apply `oconnordev-tools` to authorize the broker to assume the new role.
2. Apply `drumrollworld` to create its deploy role/policy and publish
   `drumrollworld_site_deploy_role_arn` and
   `drumrollworld_cloudfront_distribution_id` from the existing distribution.
3. Apply the `oconnordev` administrative Spacelift stack to add the repository
   configuration stack's dependency and both generated-output references to
   `drumrollworld`. Neither these outputs nor their dependency existed before
   this change.
4. Apply `oconnordev-github-repository-config` (when enabled). Its two new Actions
   variables are created only when both dependency inputs are non-empty:
   - `DRUMROLLWORLD_SITE_DEPLOY_ROLE_ARN`
   - `DRUMROLLWORLD_CLOUDFRONT_DISTRIBUTION_ID`
   The existing `OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` is reused.
   Empty bootstrap defaults allow speculative plans before the producer has
   applied; they do not make deployment operational. If these variables already
   exist outside state, import them before apply using the GitHub provider's
   `oconnordev:VARIABLE_NAME` variable import ID.
5. Rerun the failed merge-triggered workflow or manually dispatch
   **drumrollworld site** on `master`. The workflow fails before authentication
   when required variables are missing; after variables are populated, role
   setup must also have applied. No console-created credentials are required.

The workflow may run before these applies finish and fail its first deployment.
Once setup is applied, subsequent qualifying `master` pushes deploy
without additional infrastructure applies. Both site workflows run lint and
format checks after shared Biome/mise configuration changes. The existing
OConnorDev site retains its own deployment target and role.

## Validation and post-apply checks

Run `mise install --locked`, `mise run build:drumrollworld`,
`mise run test:drumrollworld`, `mise run fmt:site`, `mise run lint:site`,
`mise run workflow-lint`, `mise run fmt`, `mise run lint:python`,
`mise run lint`, `mise run validate`, `mise run test`, and `mise run checkov`.
The tests cover workflow branch/permission/path gates, exact generated-output
wiring, image preservation, pinned actions, and actual IAM JSON rendered by the
locked AWS provider without AWS calls. Biome configuration is shared by both
apps; its HTML support is explicitly enabled rather than silently skipped.
HTML formatting is experimental in the pinned Biome release. Embedded script
and style bodies are checked, but JavaScript inside HTML event-handler
attributes is not linted; keep handlers in external JS, as the OConnorDev print
action now is. Formatter strict whitespace mode preserves text-node spacing;
CSS cascade/fallback order is retained with narrowly documented suppressions.

After applying, verify the three repository variables, both role assumptions,
S3 sync success, and creation of an invalidation on the DrumrollWorld distribution.
Check `https://drumroll.world/`, its CSS/hashed JS module responses and local
decoder JS/WASM (WASM should have `application/wasm` content type). Block
`esm.sh` and `unpkg.com` in browser DevTools and verify globe initialization,
entry navigation, search and photo lightbox on desktop and a small viewport.
Confirm the existing `images/` objects survive a deployment and that removed
root code objects do not; older versioned runtime assets should remain. A
successful PR check or speculative plan is not proof of
an applied role, published app, completed invalidation, or working browser UI.

Local validation of this dependency migration on 2026-10-08 used the built
release with existing image/texture assets fetched read-only from the live
origin. Chromium rendered the textured WebGL globe on desktop and a 390px
viewport with esm.sh, unpkg.com and jsDelivr blocked. Navigation, empty-result
search/reset and photo lightbox open/close passed; no page errors, console errors
or HTTP failures were observed. This local result is not proof of deployment.

## Rollback

Revert app code on `master` and let the same pipeline publish it; alternatively,
dispatch a reviewed restoration committed to `master`. The workflow intentionally
deploys current `master`, so dispatching an old GitHub run is not a historical
release rollback. S3 versioning exists, but restoring individual historical
objects is a separate approved live operation. Disable the site workflow to
halt automation without deleting its bucket, distribution or image assets.
