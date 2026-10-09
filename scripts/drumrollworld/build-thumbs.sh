#!/usr/bin/env bash
# Default images live under the app; external recovery inputs/outputs are allowed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="${DRUMROLLWORLD_IMAGES_DIR:-$ROOT/apps/drumrollworld/images}"
OUT_DIR="${DRUMROLLWORLD_THUMBS_OUTPUT_DIR:-$SRC_DIR}"
SIZE="${THUMB_SIZE:-256}"
QUALITY="${THUMB_QUALITY:-80}"
fail() { echo "error: $*" >&2; exit 1; }
for tool in magick find node; do command -v "$tool" >/dev/null || fail "'$tool' not found in PATH"; done
[[ -d "$SRC_DIR" && -r "$SRC_DIR" ]] || fail "image source directory missing/unreadable: $SRC_DIR"
# Canonicalize once so trailing slashes and relative paths cannot leak into outputs.
SRC_DIR="$(cd "$SRC_DIR" && pwd -P)"
[[ "$SIZE" =~ ^[1-9][0-9]*$ && ${#SIZE} -le 6 ]] || fail 'THUMB_SIZE must be a positive integer <= 999999'
[[ "$QUALITY" =~ ^[1-9][0-9]?$|^100$ ]] || fail 'THUMB_QUALITY must be 1..100'
# Capture discovery in a checked command, before creating output or temp files.
# Node preserves NUL delimiters through base64; command substitution cannot.
files=$(find "$SRC_DIR" -type d \( -name globe -o -name thumbs \) -prune -o -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) ! -iname '*.thumb.*' -print0 | node -e "let b=[];process.stdin.on('data',x=>b.push(x));process.stdin.on('end',()=>process.stdout.write(Buffer.concat(b).toString('base64')))") || fail 'image discovery failed'
[[ -n "$files" ]] || fail "no eligible images in $SRC_DIR"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
printf '%s' "$files" | node -e "process.stdout.write(Buffer.from(require('fs').readFileSync(0,'utf8'),'base64'))" > "$TMP/files"
count_new=0; count_skip=0
while IFS= read -r -d '' src; do
  relative="${src#"$SRC_DIR"/}"; stem="${relative%.*}"
  out="$OUT_DIR/$stem.thumb.jpg"
  [[ "$(realpath -m "$out")" != "$(realpath "$src")" ]] || fail 'output overlaps source'
  if [[ -f "$out" && "$out" -nt "$src" && -z "${FORCE:-}" ]]; then count_skip=$((count_skip+1)); continue; fi
  mkdir -p "$(dirname "$out")"
  # Stage in the destination filesystem for atomic replacement.
  stage="$(mktemp "${out}.XXXXXX.jpg")"
  if ! magick "$src" -auto-orient -strip -resize "${SIZE}x${SIZE}>" -quality "$QUALITY" -interlace Plane -colorspace sRGB "$stage"; then rm -f "$stage"; fail "conversion failed: $src"; fi
  mv -f "$stage" "$out"; count_new=$((count_new+1))
done < "$TMP/files"
echo "done. $count_new built, $count_skip up-to-date."
