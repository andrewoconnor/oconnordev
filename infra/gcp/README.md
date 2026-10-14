# GCP stacks

`google-auth/` is a working read-only discovery root for project
`adept-presence-510022-p7` (expected number `693193037198`, name
`oconnordev-tools`). It contains a `google_project` data source, identity
postconditions, outputs and offline mock tests, not a managed project/import.

`infra/spacelift/gcp-google-auth.tf` declares the separate protected,
autodeploy-disabled `oconnordev-gcp-google-auth` stack and native Spacelift GCP
service account. Do not add GCP stacks to the AWS `local.managed_stacks` loop.

The owner must apply administrative wiring, capture its real service-account
email, grant project `roles/browser` in Cloud Shell and prove a proposed-run
read before a separate preservation-only import PR. Billing association remains
unknown. See the [runbook](../../docs/runbooks/gcp-google-auth-discovery.md) for
permissions, evidence boundaries, later import gates and rollback.

Run `mise run test:opentofu-gcp` for offline identity and rejection tests.
Existing Gmail OAuth/MCP and manually created WIF resources remain untouched.
