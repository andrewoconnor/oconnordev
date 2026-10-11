#!/usr/bin/env bash
set -euo pipefail
DIST=$1
BUCKET=$2
# Assets first; cached HTML can reference older bundles, which we retain.
while IFS= read -r -d '' file; do
  key=${file#"$DIST/"}
  cache='public,max-age=0,must-revalidate'
  if [[ "$key" =~ ^assets/main-[A-Z0-9]{8}\.js$ ]] || [[ "$key" =~ ^assets/css/resume-[a-f0-9]{64}\.css$ ]]; then
    cache='public,max-age=31536000,immutable'
  fi
  aws s3 cp "$file" "s3://$BUCKET/$key" --cache-control "$cache"
done < <(find "$DIST/assets" -type f -print0 | sort -z)
# cp refreshes metadata even for unchanged bytes, exactly once.
while IFS= read -r -d '' file; do
  key=${file#"$DIST/"}
  aws s3 cp "$file" "s3://$BUCKET/$key" --cache-control 'public,max-age=0,must-revalidate'
done < <(find "$DIST" -type f ! -path "$DIST/assets/*" ! -path "$DIST/images/*" -print0 | sort -z)
# All current root files have already been uploaded with identical sizes.
# Strongly consistent S3 listing + --size-only makes this a deletion pass.
aws s3 sync "$DIST/" "s3://$BUCKET/" --delete --size-only --exclude "assets/*" --exclude "images/*"
