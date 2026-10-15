# GCP stacks

`google-auth/` preserves adopted project `adept-presence-510022-p7` (number
`693193037198`, name `oconnordev-tools`) and declares **five new imports**:
existing manual WIF pool/provider, manual bootstrap service account (no display
name), and the two existing project browser members. The project remains a no-op;
its historical import stays idempotent. No APIs, impersonation bindings,
authoritative IAM policies, OAuth clients, billing or networks are introduced.
The owner's policy is untouched. This is adoption code, **not a completed import**.

`infra/spacelift/gcp-google-auth.tf` owns the separate protected,
autodeploy-disabled native stack and managed account outside AWS loops. Native
auth already worked in supplied run `01M4XYWS3DPJ5B2ZFPSXCG4FMV`; the unused,
incomplete manual WIF configuration is preserved, not repaired or activated.

Owner read grants are pending: project WIF Viewer and Service Account Viewer on
only the manual account. Browser already covers project-policy reads; no Service
Usage Viewer is required. See the [runbook](../../docs/runbooks/gcp-google-auth-discovery.md)
for bounded inventory anomalies, exact generated permission instructions, provider
defaults, manual OAuth boundary and owner gates.

Require a real plan with **5 imports, 0 adds, 0 changes, 0 destroys**, then zero
imports after owner-approved adoption. Stop on drift or missing permissions; never
enable APIs to force a passing plan. No live bootstrap plan/apply is claimed.

`mise run test:opentofu-gcp` copies actual configuration except dedicated
`imports.tf` (old and new imports): OpenTofu mocks cannot import. Mock creates
prove offline configuration/identity checks, never live no-change/import totals.
All nine root lockfiles remain unchanged. Existing Gmail OAuth/MCP stays manual
and untouched; no secrets or source inventory dumps belong in this repository.
