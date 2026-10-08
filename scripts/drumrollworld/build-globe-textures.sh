#!/usr/bin/env bash
# Build the globe texture set from the masters in textures/src/.
#
# Why this script exists
# ---------------------------------------------------------------------------
# A globe is almost always seen minified. At the camera altitudes this site
# uses, the GPU samples mipmap level ~3, so it never touches level 0. Shipping
# one huge level 0 therefore buys nothing: the visible pixels come from
# automatically generated, unsharpened mip levels.
#
# So this script builds every mip level itself. Each level is resampled from
# the full-resolution master with a Lanczos filter in linear light, then given
# a mild unsharp mask at that size. The result is a texture that stays crisp at
# every zoom level instead of only when fully zoomed in.
#
# Outputs, per tier (2k, 4k, 8k):
#   images/globe/earthmap<tier>.ktx2      colour, UASTC, sRGB
#   images/globe/earthnormal<tier>.ktx2   tangent-space normals, UASTC, linear
#   images/globe/earthspec<tier>.ktx2     specular mask, ETC1S, linear
#   images/globe/stars<tier>.ktx2         star field, UASTC, sRGB   (4k, 8k)
# Plus plain JPEG copies of the 2k tier, used only if KTX2 fails to load.
#
# Usage:
#   scripts/build-globe-textures.sh              # build anything out of date
#   FORCE=1 scripts/build-globe-textures.sh      # rebuild everything
#   TIERS="2048 4096" scripts/build-globe-textures.sh
#
# Requires: ImageMagick 7 (magick), KTX-Software 4.x (ktx), node.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/textures/src"
OUT="$ROOT/images/globe"
LIB="$ROOT/scripts/lib"

TIERS="${TIERS:-2048 4096 8192 10800}"
STARS_TIERS="${STARS_TIERS:-4096 8192}"
# The colour map is worth its full resolution, but relief is low frequency, so
# the normal map stops here. It also keeps GPU memory in check on phones, where
# a 10800px normal map would cost as much as the colour map itself.
NORMAL_MAX_WIDTH="${NORMAL_MAX_WIDTH:-8192}"

# Unsharp mask applied to every mip level of the colour and specular maps.
# radius x sigma + amount + threshold. Keep it mild; each level gets it once.
SHARPEN="${SHARPEN:-0x0.7+0.7+0.008}"
SHARPEN_STARS="${SHARPEN_STARS:-0x0.6+0.4+0.010}"
# Slope gain for the normal map at 2048 px wide. Scaled per level so that the
# relief keeps the same strength on every mip level. main.js scales it again
# through material.normalScale.
NORMAL_STRENGTH="${NORMAL_STRENGTH:-4.0}"
# Small blur before the Sobel pass, to keep JPEG noise out of the normals.
NORMAL_PREBLUR="${NORMAL_PREBLUR:-0x0.5}"

JPEG_QUALITY="${JPEG_QUALITY:-92}"
UASTC_QUALITY="${UASTC_QUALITY:-2}"
ZSTD_LEVEL="${ZSTD_LEVEL:-18}"

for tool in magick ktx node; do
  command -v "$tool" >/dev/null 2>&1 || { echo "error: '$tool' not found in PATH" >&2; exit 1; }
done

mkdir -p "$OUT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

tier_name() {  # 2048 -> 2k
  echo "$(( $1 / 1024 ))k"
}

mip_count() {  # 2048 -> 12 levels, down to 1x1
  local w=$1 n=1
  while (( w > 1 )); do w=$(( w / 2 )); n=$(( n + 1 )); done
  echo "$n"
}

human_size() {  # exact byte count, because du reports disk blocks
  node -e "const b=require('fs').statSync(process.argv[1]).size;process.stdout.write(b>=1048576?(b/1048576).toFixed(1)+' MiB':Math.round(b/1024)+' KiB')" "$1"
}

is_stale() {  # is_stale <output> <master>
  [[ -n "${FORCE:-}" ]] && return 0
  [[ ! -f "$1" ]] && return 0
  [[ "$2" -nt "$1" ]] && return 0
  [[ "${BASH_SOURCE[0]}" -nt "$1" ]] && return 0
  return 1
}

# Resample one mip level of an sRGB image: linear-light Lanczos, then sharpen.
# `flip` writes the rows bottom-up, which is what the KTX2 path needs.
build_srgb_level() {  # <master> <w> <h> <sharpen|none> <flip|noflip> <out.png>
  local master=$1 w=$2 h=$3 sharpen=$4 flip=$5 out=$6
  local flip_op=(); [[ "$flip" == "flip" ]] && flip_op=( -flip )
  local sharpen_op=(); [[ "$sharpen" != "none" && $w -gt 64 ]] && sharpen_op=( -unsharp "$sharpen" )
  # PNG24: forces three 8-bit channels on every level. Without it ImageMagick
  # writes small levels as paletted or grey PNGs and 'ktx create' rejects the
  # mismatched component count.
  magick "$master" -colorspace RGB -filter Lanczos -resize "${w}x${h}!" \
    -colorspace sRGB "${sharpen_op[@]}" "${flip_op[@]}" \
    -type TrueColor -depth 8 "PNG24:$out"
}

# Resample one mip level of the height map, then turn it into a normal map.
#
# Both delivery paths upload the texture bottom-up: the KTX2 files store their
# rows bottom-up, and TextureLoader sets flipY on the JPEG fallback. The green
# channel has to match, so the row direction is handled once, here:
#   flip   -> flip the height first, so image rows already run with +v
#   noflip -> keep the rows and negate the green channel with --flip-y
build_normal_level() {  # <height-master> <w> <h> <flip|noflip> <out.png>
  local master=$1 w=$2 h=$3 flip=$4 out=$5
  local gray="$TMP/h_${w}.gray" rgb="$TMP/n_${w}.rgb"
  local flip_op=() node_flag=()
  if [[ "$flip" == "flip" ]]; then flip_op=( -flip ); else node_flag=( --flip-y ); fi
  # Keep the relief strength constant across levels: coarser levels see a
  # larger height step per texel, so the gain shrinks with the level width.
  local strength
  strength=$(node -e "process.stdout.write(String(${NORMAL_STRENGTH} * ${w} / 2048))")

  magick "$master" -colorspace Gray -filter Lanczos -resize "${w}x${h}!" \
    -blur "$NORMAL_PREBLUR" "${flip_op[@]}" -depth 8 "gray:$gray"
  node "$LIB/height-to-normal.mjs" "$w" "$h" "$strength" "$gray" "$rgb" "${node_flag[@]}"
  magick -depth 8 -size "${w}x${h}" "rgb:$rgb" -type TrueColor -depth 8 "PNG24:$out"
  rm -f "$gray" "$rgb"
}

# Build a full mip chain and encode it into one KTX2 file.
encode_chain() {  # <kind: colour|normal|spec|stars> <master> <base_w> <out.ktx2>
  local kind=$1 master=$2 base_w=$3 out=$4
  local base_h=$(( base_w / 2 ))
  local levels; levels="$(mip_count "$base_w")"
  local files=() w=$base_w h=$base_h i=0

  while (( i < levels )); do
    local f="$TMP/${kind}_l${i}.png"
    case "$kind" in
      colour) build_srgb_level "$master" "$w" "$h" "$SHARPEN" flip "$f" ;;
      stars)  build_srgb_level "$master" "$w" "$h" "$SHARPEN_STARS" flip "$f" ;;
      spec)   build_srgb_level "$master" "$w" "$h" "$SHARPEN" flip "$f" ;;
      normal) build_normal_level "$master" "$w" "$h" flip "$f" ;;
    esac
    files+=( "$f" )
    w=$(( w / 2 > 0 ? w / 2 : 1 )); h=$(( h / 2 > 0 ? h / 2 : 1 )); i=$(( i + 1 ))
  done

  # KTXorientation metadata only: the rows were already flipped above. The
  # matching --convert-texcoord-origin option crashes ktx 4.4.2 on multi-level
  # input, and three's KTX2Loader ignores the metadata in any case.
  local origin=( --assign-texcoord-origin bottom-left )
  case "$kind" in
    colour|stars)
      ktx create --format R8G8B8_SRGB --assign-tf srgb --levels "$levels" "${origin[@]}" \
        --encode uastc --uastc-quality "$UASTC_QUALITY" --zstd "$ZSTD_LEVEL" \
        "${files[@]}" "$out" ;;
    normal)
      ktx create --format R8G8B8_UNORM --assign-tf linear --levels "$levels" "${origin[@]}" \
        --normalize --encode uastc --uastc-quality 3 --zstd "$ZSTD_LEVEL" \
        "${files[@]}" "$out" ;;
    spec)
      ktx create --format R8G8B8_UNORM --assign-tf linear --levels "$levels" "${origin[@]}" \
        --encode basis-lz --clevel 4 --qlevel 255 \
        "${files[@]}" "$out" ;;
  esac

  rm -f "${files[@]}"
  printf '  %-28s %s\n' "$(basename "$out")" "$(human_size "$out")"
}

echo "building globe textures from $SRC"

for w in $TIERS; do
  t="$(tier_name "$w")"
  is_stale "$OUT/earthmap$t.ktx2"    "$SRC/earthmap.jpg"   && encode_chain colour "$SRC/earthmap.jpg"    "$w" "$OUT/earthmap$t.ktx2"
  if (( w <= NORMAL_MAX_WIDTH )); then
    is_stale "$OUT/earthnormal$t.ktx2" "$SRC/earthheight.jpg" && encode_chain normal "$SRC/earthheight.jpg" "$w" "$OUT/earthnormal$t.ktx2"
  fi
  is_stale "$OUT/earthspec$t.ktx2"   "$SRC/earthspec.jpg"  && encode_chain spec   "$SRC/earthspec.jpg"   "$w" "$OUT/earthspec$t.ktx2"
done

for w in $STARS_TIERS; do
  t="$(tier_name "$w")"
  is_stale "$OUT/stars$t.ktx2" "$SRC/stars.jpg" && encode_chain stars "$SRC/stars.jpg" "$w" "$OUT/stars$t.ktx2"
done

# Plain-JPEG fallback tier. Used only when KTX2 transcoding is unavailable.
echo "building JPEG fallback tier (2k)"
if is_stale "$OUT/earthmap2k.jpg" "$SRC/earthmap.jpg"; then
  build_srgb_level "$SRC/earthmap.jpg" 2048 1024 "$SHARPEN" noflip "$TMP/fb_map.png"
  magick "$TMP/fb_map.png" -quality "$JPEG_QUALITY" -interlace Plane -strip "$OUT/earthmap2k.jpg"
fi
if is_stale "$OUT/earthnormal2k.jpg" "$SRC/earthheight.jpg"; then
  build_normal_level "$SRC/earthheight.jpg" 2048 1024 noflip "$TMP/fb_normal.png"
  magick "$TMP/fb_normal.png" -quality 96 -interlace Plane -strip "$OUT/earthnormal2k.jpg"
fi
if is_stale "$OUT/earthspec2k.jpg" "$SRC/earthspec.jpg"; then
  build_srgb_level "$SRC/earthspec.jpg" 2048 1024 "$SHARPEN" noflip "$TMP/fb_spec.png"
  magick "$TMP/fb_spec.png" -quality "$JPEG_QUALITY" -interlace Plane -strip "$OUT/earthspec2k.jpg"
fi
if is_stale "$OUT/stars4k.jpg" "$SRC/stars.jpg"; then
  build_srgb_level "$SRC/stars.jpg" 4096 2048 "$SHARPEN_STARS" noflip "$TMP/fb_stars.png"
  magick "$TMP/fb_stars.png" -quality "$JPEG_QUALITY" -interlace Plane -strip "$OUT/stars4k.jpg"
fi

echo "done."
node -e "
const fs=require('fs'),p=process.argv[1];
const files=fs.readdirSync(p).filter(f=>!f.startsWith('.'));
let total=0; for (const f of files) total+=fs.statSync(p+'/'+f).size;
console.log(files.length+' files, '+(total/1048576).toFixed(1)+' MiB in images/globe');
" "$OUT"
