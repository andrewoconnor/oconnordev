#!/usr/bin/env bash
# Generate small JPEG thumbnails next to each entry image.
# Originals are left untouched. Output: <dir>/<name>.thumb.jpg
#
# Used by globe markers (see main.js) so first-paint payload stays tiny.
# Re-run after adding new images; existing up-to-date thumbs are skipped.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT/images"
SIZE=256          # max edge in px
QUALITY=80        # JPEG quality

if ! command -v magick >/dev/null 2>&1; then
  echo "error: ImageMagick 'magick' not found in PATH" >&2
  exit 1
fi

count_new=0
count_skip=0

while IFS= read -r -d '' src; do
  # skip our own thumbs
  case "$src" in *.thumb.jpg) continue ;; esac

  dir="$(dirname "$src")"
  base="$(basename "$src")"
  stem="${base%.*}"
  out="$dir/$stem.thumb.jpg"

  if [[ -f "$out" && "$out" -nt "$src" ]]; then
    count_skip=$((count_skip + 1))
    continue
  fi

  magick "$src" \
    -auto-orient \
    -strip \
    -resize "${SIZE}x${SIZE}>" \
    -quality "$QUALITY" \
    -interlace Plane \
    -colorspace sRGB \
    "$out"

  printf '  %s  ->  %s\n' "${src#$ROOT/}" "${out#$ROOT/}"
  count_new=$((count_new + 1))
done < <(find "$SRC_DIR" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) \
           -not -path '*/globe/*' -print0)

echo "done. $count_new built, $count_skip up-to-date."
