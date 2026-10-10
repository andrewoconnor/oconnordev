# Owned no-eval Basis transcoder

These JS and WASM files are a **matched pair**, compiled together from unmodified
Binomial Basis Universal v1.50.0 source, commit
`051ad6d8a64bb95a79e8601c317055fd1782ad3e`:
https://github.com/BinomialLLC/basis_universal/tree/051ad6d8a64bb95a79e8601c317055fd1782ad3e

Three's shipped runtime was upgraded to Basis v1.50 in commit
`302240259d4ae8ae54557f7be6f0515a662f256d`:
https://github.com/mrdoob/three.js/commit/302240259d4ae8ae54557f7be6f0515a662f256d
This retains that Basis release family, not current upstream master. We do not
claim the rebuilt WASM is interchangeable with Three's shipped JS or vice versa.
Three and other npm package versions and lockfiles are unchanged.

## Rebuild

Toolchain: Emscripten **4.0.19**, emsdk tag commit
`7b4e60e4bfcba326025e373024369eaa9904af55`, SDK release
`8b01e2ec3f33e6b94842096d7312ce4ef5f33f6c`; CMake 3.31.6 on Linux x86_64.
Install/activate that SDK and source `emsdk_env.sh`, then run:

```sh
bash rebuild.sh /absolute/path/to/new/scratch-directory
```

The script compiles upstream `webgl/transcoder/CMakeLists.txt` unchanged, adding
`-s DYNAMIC_EXECUTION=0 -s EXPORTED_RUNTIME_METHODS=HEAP8` through CMake's linker
flags. The first option selects Emscripten's supported non-dynamic embind/emval
paths; the second exposes the heap used by this upstream wrapper with the newer
compiler. KTX2 and Zstandard stay enabled. There is no generated-JS rewriting,
source patch, custom invoker implementation, or node_modules mutation.

`SHA256SUMS` pins both delivered files, including the **decoded binary** WASM,
not its transport representation. To support the UTF-8-only repository gateway,
WASM is stored as `basis_transcoder.wasm.base64`: canonical RFC 4648 Base64 on
one line followed by LF. The app build rejects invalid alphabet, padding,
whitespace and nonzero padding bits, decodes locally, checks the unchanged binary
hash, and publishes only `basis_transcoder.wasm` (never the Base64 file).
The rebuild verifies binary output hashes before copying JS and encoding WASM;
normal app builds require neither network nor Emscripten.

## License and behavioral verification

Basis Universal is Apache-2.0, with the complete upstream `LICENSE` included.
Its embedded Zstandard attribution remains in `../EMBEDDED-LICENSES.txt`, shipped
in the application's third-party notices. Emscripten generated runtime is covered
by its MIT/University of Illinois NCSA licenses (see `EMSCRIPTEN-LICENSE.txt`).

The actual-HCL CSP browser regression requires seven real KTX2 transcodes through
Three's blob worker, zero compatibility violations/page errors, and a same-origin
script's `Function` probe to be blocked. CSP permits `wasm-unsafe-eval` for WASM
compilation, **not** `unsafe-eval` for JavaScript. Test fixtures are synthetic
artwork encoded by the real pipeline, not production assets.
