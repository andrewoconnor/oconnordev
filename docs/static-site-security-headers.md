# Static-site CSP and Permissions-Policy

## Scope and compatibility tradeoff

Both existing CloudFront response headers policies now enforce an overriding CSP
and Permissions-Policy. Distribution settings, origin authentication, cache TTLs,
forwarding, existing security headers, dependency pins and lockfiles are unchanged.
No publication or cloud change was performed.

The resume remains strict: `default-src 'none'`, same-origin stylesheets/images,
and only the byte-exact inline JSON-LD script hash
`4JHmSUmc1wePxlVTxsVTwn6GgpQ+Oa79jBlKuyYIE5c=`. It does not allow JavaScript eval,
inline executable scripts, script/style attributes, connections, objects, base
URLs, forms, embedding, third-party origins, wildcards, blob or data URLs.
The browser regression recomputes the JSON-LD hash from the generated HTML.

DrumrollWorld uses `script-src 'self' 'wasm-unsafe-eval'`, with **no JavaScript
unsafe-eval exception**. Three 0.186.1's shipped Basis runtime dynamically creates
embind invokers with `Function`, so replacing only its policy would break KTX2.
The app instead publishes an owned, matched JS/WASM pair rebuilt from unmodified
Basis Universal v1.50.0 (`051ad6d8a64bb95a79e8601c317055fd1782ad3e`), retaining
the release family previously shipped by Three. Emscripten 4.0.19's supported
`DYNAMIC_EXECUTION=0` paths remove the need for JavaScript string execution;
`EXPORTED_RUNTIME_METHODS=HEAP8` exposes the heap required by that upstream wrapper.
Both outputs have pinned SHA-256 hashes, full license attribution and a rebuild
script in `apps/drumrollworld/third-party/basis-1.50.0-no-eval/`. A second clean
source/build directory reproduced both pinned hashes. Normal app builds verify
and copy vendored assets offline, without compiler installation or npm mutation.
The UTF-8-only publication gateway requires WASM to be checked in as canonical
single-line `basis_transcoder.wasm.base64` plus LF. Builds strictly validate and
decode this transport file, then verify the original binary SHA-256 before
publishing the unchanged `.wasm`; Base64 is not shipped to browsers. Rebuilds
verify the same binary hashes before encoding the repository representation.
The real-worker browser test requires seven KTX2 transcodes and blocked `Function`
execution. `wasm-unsafe-eval` permits WASM compilation only; it does not permit
JavaScript eval in the document or inherited-CSP blob workers.

Other Drumroll allowances remain narrow:

- `worker-src blob:` for Three KTX2Loader's workers; they inherit document CSP.
- `connect-src 'self'` for local texture, JS and WASM downloads.
- `img-src 'self' data: blob:` for artwork, CSS's embedded close-icon SVG, and
  Three image/blob capability. Browser tests actually decode data/blob images.
- `style-src-attr 'unsafe-inline'` for dynamic scene/panel/tooltip/search styles;
  executable script attributes remain denied.
- `style-src 'self'` plus byte-exact style-element hashes, rather than blanket
  style-element unsafe-inline:
  - standalone 404: `1OVkcrOQP7NV9SqPTIZQMVnSWqtceFiWV3g5XyDm98A=`;
  - float-tooltip-kap: `9xjtvxMT1ApHlgn9ohbh2FNfvK5Tqtzy94BjfXBeMSY=`;
  - scene-nav-info: `yfc2FhpkFR0EAy3T+zDsaAFGXSP9B3ELNvaJKDzNhkk=`;
  - scene-container clickable: `GRFgt45UbKYCV14/Fqy6H9EB3zlAwSnH4xbsYt03Q6M=`;
  - empty style before library text assignment:
    `47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=`.

Both Permissions-Policy values disable accelerometer, autoplay, camera,
display-capture, encrypted-media, fullscreen, geolocation, gyroscope,
magnetometer, microphone, MIDI, payment, picture-in-picture,
publickey-credentials-get, screen-wake-lock, USB and xr-spatial-tracking.
Neither app uses these features; WebGL itself is not disabled. Browsers ignore
unsupported names. Chromium readback verifies camera, microphone, geolocation,
payment, USB and fullscreen denied.

## Verification and reproduction

The runner serves fresh builds locally using **actual Terraform literal HTTP
headers**, not a meta tag or diagnostic candidate. Its default full run covers
resume, Drumroll globe, WebGL-unavailable fallback and the standalone HTTP 404.
It checks zero compatibility CSP violations and page errors, local-only requests,
UI navigation/search/gallery/lightbox/responsive behavior, genuine KTX2 worker
messages, permissions denial, and rejection of both inline and foreign scripts
and foreign fetches. A same-origin script probes real `Function` execution,
which must be blocked on Drumroll; DevTools evaluation is not used as
proof of eval permission. Exact mock assertions lock both policies and overrides,
including strict resume scripts and WASM-only Drumroll compilation.

The fixtures in `/opt/data/cache/scratch/drumrollworld-real-pipeline-proof` have
synthetic content but are genuinely encoded 16px KTX2 and JPEG files. The local
server maps normal same-origin image URLs to them without modifying the app,
faking WebGL/WASM/transcode results or contacting remote sites in globe mode.
This proves policy/runtime compatibility, not production artwork/size or CDN
behavior. WebGL-unavailable mode intentionally simulates context-creation failure.
The local server models existing CloudFront 404 mapping; it is not a deployed-CDN
readback. Fixture generation is outside this headers change.

Reused existing npm dependencies, provider cache and browser; npm pins and
lockfiles are unchanged. Installed Emscripten 4.0.19 locally for the authorized
runtime rebuild (1.7 GB under `/opt/data/tools/drumrollworld/emsdk-4.0.19`).
No cloud writes or publication occurred. Resume node_modules is an ignored
symlink to the existing resume worktree; Drumroll dependencies were hardlink-copied
because esbuild's existing single-Three validator requires local real paths.

```sh
export TF_PLUGIN_CACHE_DIR=/opt/data/.opentofu.d/plugin-cache
export PATH=/opt/data/.local/share/mise/installs/opentofu/1.12.6:/opt/data/.local/share/mise/installs/tflint/0.64.0:$PATH
export PLAYWRIGHT_BROWSERS_PATH=/opt/data/cache/scratch/oconnordev-playwright
export DRUMROLL_FIXTURES=/opt/data/cache/scratch/drumrollworld-real-pipeline-proof
node apps/oconnordev/build.js
node apps/drumrollworld/build.js
for stack in production drumrollworld; do
  tofu -chdir=infra/aws/$stack init -backend=false -input=false -no-color -lockfile=readonly
  tofu -chdir=infra/aws/$stack fmt -check
  tofu -chdir=infra/aws/$stack validate -no-color
  tofu -chdir=infra/aws/$stack test -no-color
  tflint --chdir=infra/aws/$stack -f compact
done
timeout 180 node scripts/security/static-site-headers.test.cjs
npm --prefix apps/oconnordev test
npm --prefix apps/drumrollworld test
```

Completed local verification: both roots pass fmt, validate and TFLint; production
mock tests report **1 passed, 0 failed**, Drumroll **3 passed, 0 failed** (including
existing gzip and 404 tests). Checkov reports production **127 passed, 0 failed,
19 skipped** and Drumroll **71 passed, 0 failed, 9 skipped**, preserving existing
skips. The runner passes Biome format/lint using the existing scratch config with
repository-equivalent rules (repository Biome includes only apps). Both fresh builds succeeded. The full default
actual-HCL browser run exited 0 across all four modes, including **seven real KTX2
transcodes**, zero compatibility violations, zero page errors and all attack
assertions passing. Drumroll's `javascriptEvalBlocked` is **true** in globe,
fallback and 404 modes. Drumroll app tests pass **16/16** after the runtime change.
The new rebuild script reproduced both byte hashes in a separate clean directory.
Upstream compilation emits existing C++11/`memcpy` and CMake deprecation warnings;
no source patches were applied. Two initial browser runs timed out waiting for
the loading screen on this shared machine; isolated modes and the final complete
four-mode run passed without changing timeouts or weakening assertions.

## Rollout and rollback

Review the local diff before publication/apply. Ensure current build artifacts and
Drumroll `/404.html` are published before activating the corresponding headers;
changing inline JSON-LD, injected style bytes or runtime libraries requires updated
hashes and another full browser run. After an authorized deployment, read actual
CloudFront headers for both pages and a missing Drumroll path, and repeat browser
checks with production artwork. This task has not applied or verified live headers.
Rollback the headers and runtime artifacts together if reverting to Three's
original Basis pair, since that runtime needs JavaScript dynamic execution.
Do not activate this CSP with the old runtime. Retain existing HSTS, nosniff,
framing/referrer headers and delivery behavior.
