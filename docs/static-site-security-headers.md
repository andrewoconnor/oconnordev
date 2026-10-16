# Static-site CSP and Permissions-Policy

## Scope and compatibility tradeoff

Both CloudFront response headers policies override origin CSP and
Permissions-Policy. The [local module](../infra/modules/static-site/README.md)
owns delivery behavior; each workload supplies its byte-exact CSP.

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
Basis Universal v1.50.0 (`051ad6d8a64bb95a79e8601c317055fd1782ad3e`), using
the pinned release family. Emscripten 4.0.19's supported
`DYNAMIC_EXECUTION=0` paths remove the need for JavaScript string execution;
`EXPORTED_RUNTIME_METHODS=HEAP8` exposes the heap required by that upstream wrapper.
Both outputs have pinned SHA-256 hashes, full license attribution and a rebuild
script in `apps/drumrollworld/third-party/basis-1.50.0-no-eval/`. Normal app builds verify
and copy vendored assets offline, without compiler installation or npm mutation.
The UTF-8-only publication gateway requires WASM to be checked in as canonical
single-line `basis_transcoder.wasm.base64` plus LF. Builds strictly validate and
decode this transport file, then verify the original binary SHA-256 before
publishing the unchanged `.wasm`; Base64 is not shipped to browsers. Rebuilds
verify the same binary hashes before encoding the repository representation.
The real-worker browser test requires the exact GPU-dependent KTX2 transcode
count and blocked `Function` execution. `wasm-unsafe-eval` permits WASM compilation only; it does not permit
JavaScript eval in the document or inherited-CSP blob workers.

Other Drumroll allowances remain narrow:

- `worker-src blob:` for Three KTX2Loader's workers; they inherit document CSP.
- `connect-src 'self'` for local texture, JS and WASM downloads.
- `img-src 'self' data: blob:` for artwork, CSS's embedded close-icon SVG, and
  Three image/blob capability. Browser tests actually decode data/blob images.
- `media-src 'self'` for self-hosted entry videos. Browser tests check that
  same-origin media loads and that third-party media is blocked.
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

The runner uses vendored, hash-verified genuine upstream fixtures; see
[fixture provenance](../scripts/security/fixtures/README.md). They prove decoder
and CSP compatibility, not production artwork, texture size, CDN behavior or
GPU performance. WebGL-unavailable mode simulates context-creation failure.

```sh
mise run build:oconnordev
mise run test:oconnordev
mise run build:drumrollworld
mise run test:drumrollworld
mise run test:opentofu-delivery
```

Build tasks install the locked application dependencies; browser installation
and cache requirements are described in fixture provenance. A passing local run
is not live CloudFront header verification.

## Rollout and rollback

Review the local diff before publication/apply. Ensure current build artifacts and
Drumroll `/404.html` are published before activating the corresponding headers;
changing inline JSON-LD, injected style bytes or runtime libraries requires updated
hashes and another full browser run. After an authorized deployment, read actual
CloudFront headers for both pages and a missing Drumroll path, and repeat browser
checks with production artwork. Local checks do not establish deployed headers.
Review headers and runtime artifacts together for rollback. Never pair this CSP
with a decoder requiring JavaScript dynamic execution. Retain existing HSTS, nosniff,
framing/referrer headers and delivery behavior.
