#!/usr/bin/env bash
#
# Deploy the Hermes AgentCore adapter from its repository checkout.
#
# The adapter is a checkout of this repository rather than a build artifact, so
# "deploying" means fast-forwarding that checkout and then reloading the MCP
# server the agent runs it from. Doing either by hand is how a stale adapter
# stays in service: it keeps answering, with the previous release's tool-name
# mapping, and the symptom is tools that are missing or that the gateway does
# not recognise rather than anything that looks like a failed deploy.
#
# This refuses to run against a dirty checkout -- a hand-patched copy is exactly
# the state this exists to prevent -- then updates it, runs the adapter's own
# tests, and smoke-tests the deployed registration against the live gateway.
#
# The reload itself is a step only the agent can perform, so this cannot finish
# quietly: it exits 2 until the reload is confirmed. Pass --reloaded once you
# have run /reload-mcp, or set HERMES_ADAPTER_RELOAD_CMD to something that
# performs it.
#
# Exit codes: 0 deployed and reloaded, 1 a step failed, 2 deployed, reload pending.
#
# Usage (the file is committed 0644, so invoke it through bash):
#   bash scripts/deploy_hermes_adapter.sh [--checkout DIR] [--rev REF]
#                                        [--server NAME] [--reloaded] [--skip-tests]

set -euo pipefail

CHECKOUT="${HERMES_ADAPTER_CHECKOUT:-/opt/data/hermes-agentcore-adapter}"
REV="master"
SERVER="agentcore"
RELOADED=0
SKIP_TESTS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --checkout) CHECKOUT="$2"; shift 2 ;;
    --rev)      REV="$2"; shift 2 ;;
    --server)   SERVER="$2"; shift 2 ;;
    --reloaded) RELOADED=1; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

step() { printf '\n== %s\n' "$1"; }
die()  { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

step "Checking the checkout at $CHECKOUT"
[ -d "$CHECKOUT/.git" ] || die "$CHECKOUT is not a git checkout; this deploys a checkout, never a copied tree"
git -C "$CHECKOUT" rev-parse --quiet --verify HEAD >/dev/null || die "$CHECKOUT has no commit checked out"

# A dirty tree means someone edited the deployed copy directly. Deploying over it
# would hide that, and whatever was changed would silently vanish.
if [ -n "$(git -C "$CHECKOUT" status --porcelain)" ]; then
  git -C "$CHECKOUT" status --short >&2
  die "the checkout is dirty. Commit the change and deploy it through the repository, or reset the checkout."
fi

BEFORE="$(git -C "$CHECKOUT" rev-parse --short HEAD)"
printf '  at %s, clean\n' "$BEFORE"

step "Updating to origin/$REV"
git -C "$CHECKOUT" fetch --quiet origin "$REV"
git -C "$CHECKOUT" merge --ff-only --quiet "origin/$REV" || die "cannot fast-forward to origin/$REV; the checkout has diverged"
AFTER="$(git -C "$CHECKOUT" rev-parse --short HEAD)"
if [ "$BEFORE" = "$AFTER" ]; then
  printf '  already at %s, nothing to update\n' "$AFTER"
else
  printf '  %s -> %s\n' "$BEFORE" "$AFTER"
fi

if [ "$SKIP_TESTS" -eq 0 ]; then
  step "Running the adapter tests"
  ( cd "$CHECKOUT/agents/hermes/adapter" && "$PYTHON" -m unittest discover -s test -t . -q ) \
    || die "the adapter tests failed; not deploying"
  printf '  passed\n'
fi

step "Smoke-testing the deployed registration against the live gateway"
# This is the step that catches a manifest and a gateway that disagree about how
# many namespace levels a tool name carries -- the failure that otherwise shows
# up as missing tools long after the deploy looked fine.
"$PYTHON" "$SCRIPT_DIR/adapter_smoke_test.py" --checkout "$CHECKOUT" --server "$SERVER" \
  || die "the deployed adapter does not agree with the gateway; not reloading"

step "Reloading the adapter"
if [ -n "${HERMES_ADAPTER_RELOAD_CMD:-}" ]; then
  printf '  running HERMES_ADAPTER_RELOAD_CMD\n'
  sh -c "$HERMES_ADAPTER_RELOAD_CMD" || die "HERMES_ADAPTER_RELOAD_CMD failed"
  printf '  reloaded\n'
elif [ "$RELOADED" -eq 1 ]; then
  printf '  confirmed by --reloaded\n'
else
  cat >&2 <<'MSG'

  Deployed and verified, but the running MCP server still holds the previous
  code in memory. Reload it before using the tools:

      /reload-mcp

  then re-run the smoke test, or re-run this script with --reloaded to record
  that the step is done.
MSG
  exit 2
fi

printf '\nDeployed %s (%s), reloaded, and verified against the gateway.\n' "$AFTER" "$SERVER"
