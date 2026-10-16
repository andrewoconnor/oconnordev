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

The check job builds/lints/tests the exact `github.sha` once and uploads a
pinned Actions artifact containing the tested public bytes. Deployment downloads
that same-run artifact by SHA-qualified name, verifies the check job's SHA256
before extraction and AWS credentials, and never rebuilds or checks out moving
`master`. Both jobs have bounded timeouts. Pre-credential app-scoped freshness validation compares tested inputs with
fetched master and rejects relevant changes; docs/infrastructure-only successors
can retain the tested artifact. Concurrency serializes each site's runs
without cancelling an active publication. A newer merge during publication is
handled by the next run. S3 publication is not an atomic release switch.

The `drumrollworld-production` GitHub environment allows deployments only from
branch `master` (no tag rule). Its exact OIDC subject is
`repo:andrewoconnor/oconnordev:environment:drumrollworld-production`; audience is
`sts.amazonaws.com`. Environment subjects do not include a ref: GitHub must
apply the deployment-branch gate **before** a runner can request that token.
The dedicated `drumrollworld-github-actions-broker` in TOOLS can assume only
`drumrollworld-site-deploy` in PRODUCTION. The OConnorDev broker is independently
restricted to its own environment and site role; neither site's identity can
chain into the other site. The brokers are separate site identities. No AWS access keys are stored in GitHub.

## Images and globe textures are outside this checkout

The app references external `images/` photographs, videos, favicon and
KTX2/globe tiers. They are not fully reproducible from this repository. Use the
[image-recovery runbook](drumrollworld-image-recovery.md) for verified local
restoration, original-master inventory and regeneration. Versioning is enabled;
noncurrent versions expire after 30 days and incomplete multipart uploads after
7 days. Versioning is not an independent backup and cannot cover account/region
loss, privileged version deletion or expired versions.

The workflow excludes `images/*` and prior `assets/*` from root sync/deletion.
See `.github/workflows/drumrollworld-site.yml` for the complete publication
commands, including cache metadata and deletion-only root reconciliation.

AWS CLI excludes matching destination objects from deletion. The deploy role
also explicitly denies `s3:DeleteObject` on `drumrollworld-web/images/*`, so a
future accidental removal of the exclusion cannot delete existing images.
Root code objects removed from the release are still deleted. Runtime assets
are uploaded first without deletion, then excluded from the root sync. Older
hashed modules and versioned decoder assets remain available while cached HTML
and open clients still reference them. This is not an atomic release switch;
asset cleanup needs a separate reviewed retention procedure, not an unbounded
`--delete` during publication. The workflow does
not upload or self-copy image bytes. Image publication needs a separate explicit
procedure or future versioned asset-source design. Do not remove the exclusions
without separately reviewing asset ownership. The repository-owned SVG fallback is outside
`images/` and is included in the release.

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

Both sites use the same publication helper: one `s3 cp` per file supplies final
cache metadata, assets before root/HTML. Only content-hashed DrumrollWorld JS and
OConnorDev SHA256 CSS are immutable. Stable HTML and other assets revalidate.
The final root `sync --delete --size-only` excludes `assets/*` and `images/*`.
All current root files have already been uploaded at identical sizes; S3's
strongly consistent listing and size-only comparison skip their upload, leaving
only stale root deletions. The offline regression executes the real pinned AWS
CLI dry-run planner against a local S3 listing and checks zero second uploads,
old hashed/image preservation, and deletion of stale root files. cp deliberately
refreshes unchanged metadata once per deployment, with associated request/version
costs. CloudFront invalidation cannot recall existing browser caches.

Build diagnostics live in `apps/drumrollworld/.build/build-meta.json`, outside
`dist/`, and must never enter the release artifact. Verify `/build-meta.json`
returns a real 404. No recurring image self-copy or GetObject repair privilege
belongs in site deployment. Check every referenced KTX2 path for readability,
`image/ktx2` and mutable revalidation metadata before publishing new references.
Local tests do not prove live environment enforcement or deployed bytes.

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

## Compression and real 404 behavior

The shared module enables `compress = true` for both sites and uses AWS Managed-CachingOptimized (`658327ea-f89d-4fab-a63d-7e88639e58f6`) with normalized Accept-Encoding cache keys for Gzip/Brotli, no query strings or cookies. Managed TTLs are minimum 1s, default 86400s, maximum 31536000s; HTML may be cached for at least one second; objects without Cache-Control inherit the default. Review metadata on manually published images.

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

When changing delivery behavior, publish and verify `/404.html` first, then
have the owner review/apply the workload plan. After distribution deployment,
run the master workflow and wait for invalidation. From an allowed country,
check the current hashed JS with `Accept-Encoding: gzip` and a new missing URL:
expect eligible JS compression and an HTML **404**, not S3 XML or the app shell.
Geographic denials are not missing-object tests. Inspect deployment/invalidation
completion and response eligibility before changing TTLs or permissions.

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

## Environment bootstrap

Follow [the shared bootstrap sequence](infrastructure-bootstrap.md#tested-artifact-environment-bootstrap)
for a new environment. Pause workflows until owner-reviewed applies, master-only
branch-gate readback and enforcement checks pass. Qualifying master pushes use
tested artifacts; a workflow merge does not apply IAM or GitHub environments.

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
action is. Formatter strict whitespace mode preserves text-node spacing;
CSS cascade/fallback order is retained with narrowly documented suppressions.

After applying, verify the three DrumrollWorld Actions variables, both role assumptions,
S3 sync success, and creation of an invalidation on the DrumrollWorld distribution.
Check `https://drumroll.world/`, its CSS/hashed JS module responses and local
decoder JS/WASM (WASM should have `application/wasm` content type). Block
`esm.sh` and `unpkg.com` in browser DevTools and verify globe initialization,
entry navigation, search and photo lightbox on desktop and a small viewport.
Confirm the existing `images/` objects survive a deployment and that removed
root code objects do not; older versioned runtime assets should remain. A
successful PR check or speculative plan is not proof of
an applied role, published app, completed invalidation, or working browser UI.

## Rollback

Revert app code on `master` and let the same pipeline publish it; alternatively,
dispatch a reviewed restoration committed to `master`. The workflow deploys only its tested bytes after app-scoped current-master
freshness validation; changed release inputs reject a stale run rather than
rebuilding untested bytes. S3 versioning exists, but restoring individual object versions is a separate approved live operation. Disable the site workflow to
halt automation without deleting its bucket, distribution or image assets.
