#!/usr/bin/env bash
# Rebuild unmodified upstream sources; requires Git, CMake and Emscripten 4.0.19.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work=${1:?Usage: bash rebuild.sh /absolute/scratch-directory}
[[ "$work" = /* ]] || { printf '%s\n' 'Scratch directory must be absolute' >&2; exit 1; }
[[ "$(emcc --version)" == *'4.0.19'* ]] || { printf '%s\n' 'Emscripten 4.0.19 required' >&2; exit 1; }
mkdir -p "$work"
git init "$work/source"
git -C "$work/source" remote add origin https://github.com/BinomialLLC/basis_universal.git
git -C "$work/source" fetch --depth 1 origin 051ad6d8a64bb95a79e8601c317055fd1782ad3e
git -C "$work/source" checkout --detach FETCH_HEAD
emcmake cmake -S "$work/source/webgl/transcoder" -B "$work/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXE_LINKER_FLAGS='-s DYNAMIC_EXECUTION=0 -s EXPORTED_RUNTIME_METHODS=HEAP8'
cmake --build "$work/build" --parallel 2
(cd "$work/build" && sha256sum -c "$here/SHA256SUMS")
# Verify before replacing the owned assets. Ordinary app builds never need a compiler.
cp "$work/build/basis_transcoder.js" "$here/"
# Canonical single-line Base64 plus LF for the UTF-8-only repository gateway.
base64 -w 0 "$work/build/basis_transcoder.wasm" > "$here/basis_transcoder.wasm.base64"
printf '\n' >> "$here/basis_transcoder.wasm.base64"
