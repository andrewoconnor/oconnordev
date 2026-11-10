#!/usr/bin/env bash
set -euo pipefail
DEST=$1
[[ "$RUN_ID" =~ ^[0-9]+$ && "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Unexpected run identity" >&2; exit 1; }
id=$(gh api "repos/$REPOSITORY/actions/runs/$RUN_ID/artifacts?name=$NAME" | jq -er \
  --arg name "$NAME" --argjson run "$RUN_ID" --arg sha "$SHA" \
  '[.artifacts[] | select(.name == $name and .workflow_run.id == $run and .workflow_run.head_sha == $sha and (.expired | not))]
   | if length == 1 then .[0].id else error("expected exactly one artifact from this run") end')
archive=$(mktemp)
trap 'rm -f "$archive"' EXIT
gh api "repos/$REPOSITORY/actions/artifacts/$id/zip" > "$archive"
mkdir -p "$DEST"
unzip -q "$archive" -d "$DEST"
