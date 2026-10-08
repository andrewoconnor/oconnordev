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

The deployment command deliberately excludes this prefix:

```sh
mise exec -- aws s3 sync apps/drumrollworld/dist/assets/ s3://drumrollworld-web/assets/
mise exec -- aws s3 sync apps/drumrollworld/dist/ s3://drumrollworld-web/ --delete --exclude "images/*" --exclude "assets/*"
```

AWS CLI excludes matching destination objects from deletion. The deploy role
also explicitly denies `s3:DeleteObject` on `drumrollworld-web/images/*`, so a
future accidental removal of the exclusion cannot delete existing images.
Root code objects removed from the release are still deleted. Runtime assets
are uploaded first without deletion, then excluded from the root sync. Older
hashed modules and versioned decoder assets remain available while cached HTML
and open clients still reference them. This is not an atomic release switch;
asset cleanup needs a separate reviewed retention procedure, not an unbounded
`--delete` during publication. The workflow does
not upload or manage images, including images added to the checkout later;
asset publication needs a separate explicit procedure or a future versioned
asset-source design. Do not remove the exclusion without migrating that asset
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
After the original deployment bootstrap, this code-only update needs no new
Terraform resources, IAM permissions or infrastructure apply: merge it to
`master` and the existing workflow builds, syncs and invalidates CloudFront.

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
