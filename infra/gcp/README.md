# GCP stacks

`google-auth/` declares preservation-only adoption of project
`adept-presence-510022-p7` (number `693193037198`, name `oconnordev-tools`).
It retains independent discovery, adds one protected `google_project` and one
declarative import. This is stage-two code, **not a completed import**.

The native free-account discovery run `01M4XYWS3DPJ5B2ZFPSXCG4FMV` FINISHED
with exact identity outputs (stage-one evidence supplied by the owner).
Cloud Shell metadata reports ACTIVE, no labels or parent; billing describe
reports `billingEnabled: false` with `billingAccountName` omitted. Do not attach
billing, enable APIs, change IAM or assume broad billing visibility.

`infra/spacelift/gcp-google-auth.tf` owns the separate protected,
autodeploy-disabled native stack/integration, outside the AWS stack loop.
Only the owner approves import apply after a real plan shows **1 import,
0 adds, 0 changes, 0 destroys**, and no drift. See the
[runbook](../../docs/runbooks/gcp-google-auth-discovery.md).

Run `mise run test:opentofu-gcp` for offline tests. The runner copies production
configuration except `imports.tf`: OpenTofu mock providers cannot import.
Mock creation proves configuration checks, never a live import/no-change plan.
Existing Gmail OAuth/MCP and manual WIF resources remain untouched.
