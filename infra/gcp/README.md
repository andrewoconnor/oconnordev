# GCP stacks

`google-auth/` preserves adopted project `adept-presence-510022-p7` (number
`693193037198`, name `oconnordev-tools`) and five existing bootstrap objects:
manual WIF pool/provider, manual service account without a display name, and two
project browser members. Supplied run `01M4ZV628AS0TYRQGFDKEWDF55` FINISHED
that bootstrap adoption. All six historical imports must now be no-op.

Stage three adopts **two existing owner-granted read memberships** for native
`gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com`:
project `roles/iam.workloadIdentityPoolViewer` and
`roles/iam.serviceAccountViewer` on **only** manual account
`spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com`.
Both are unconditional, additive single-member resources with `prevent_destroy`.
No permission expansion, authoritative policies, APIs, impersonation grants,
credentials, OAuth clients, billing or networks are introduced. SA Viewer also
allows key-metadata get/list; it does not allow key creation, signing or token
minting. Existing Browser and SA Viewer cover the provider's IAM-policy reads;
no additional read grants or Service Usage Viewer are needed.

`infra/spacelift/gcp-google-auth.tf` still owns the separate protected,
autodeploy-disabled native stack/integration outside AWS loops. Native auth and
unused incomplete manual WIF remain unchanged; this is not an auth repair.

Require the exact published revision's real native proposed plan with **2 imports,
0 adds, 0 changes, 0 destroys**, eight managed objects plus existing discovery
data, all six historical objects no-op and no unknowns/drift. After owner-approved
adoption require zero imports and no changes. The two-import live plan has **not**
yet run; publication, exact-head CI, real plan review and owner apply remain gates.
See the [runbook](../../docs/runbooks/gcp-google-auth-discovery.md) for import
formats, supplied evidence, bundled disclosure, provider reads and stop conditions.

`mise run test:opentofu-gcp` copies actual configuration except `imports.tf`:
OpenTofu mocks cannot import. Eight mock creates prove offline configuration,
never live no-change/import totals. All nine root lockfiles stay unchanged.
Existing Gmail OAuth/MCP remains manual and untouched; no secrets or inventory
dumps belong in this repository.
