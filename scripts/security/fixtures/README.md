# Browser fixture provenance

These are unchanged **genuine upstream sample bytes**, vendored so the browser
proof needs no network, encoder/compiler, production S3 access or manual fixture
environment. `provenance.json` pins every source URL to Basis Universal commit
`051ad6d8a64bb95a79e8601c317055fd1782ad3e` (v1_50_0), file length and SHA-256.
The original binaries are stored as `kodim23.ktx2.base64` and
`kodim18_64x64.png.base64` for UTF-8-only publication. Each file is canonical RFC
4648 base64 (standard alphabet and padding, no wrapping, exactly one final LF).
The runner strictly decodes them into Buffers in memory before launching and
checks both lengths and SHA-256 against the **original binary** manifest, not
against the encoded text. No generated binary files or external fixtures are
required. Noncanonical encoding, missing files, wrong lengths and wrong hashes
fail closed. The unchanged upstream license is retained in
`LICENSE.basis-universal` (Apache-2.0).

- `kodim23.ktx2`: upstream encoded Kodak test image, 768×512, 10 mip levels,
  UASTC with Zstandard supercompression. The real vendored no-eval Basis worker
  decodes it at each requested globe tier; the browser must report the exact
  GPU-dependent transcode count. All texture names intentionally use this one
  sample: this proves CSP/decoder compatibility, not production artwork, tier
  resolution, image quality or download-performance coverage.
- `kodim18_64x64.png`: upstream small test image for the gallery/JPEG fallback
  routes (served as image/png), including blob/data image decoding.

Reproduce locally with the existing pinned tools:

```sh
mise run build:drumrollworld
mise exec -- node apps/drumrollworld/node_modules/playwright/cli.js install chromium --only-shell
mise run test:drumrollworld
```

The npm lock pins Playwright 1.64.0 and therefore Chrome Headless Shell
156.0.8078.4, revision 1248. CI installs that browser (and its required system
libraries) during the build task; there is no ambient system-Chromium fallback.
On hosts that override `PLAYWRIGHT_BROWSERS_PATH` with a shared/locked runtime
cache, set it to a private writable cache before installing and testing.
For resume, use `build:oconnordev` and `test:oconnordev`; its existing Playwright
pin is identical. `SITES` limits the runner to the built site, so DrumrollWorld
checks do not install/build the resume. Tests themselves use only loopback and
abort any external browser requests.
