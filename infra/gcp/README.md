# GCP stacks

`google-auth/` declares project `adept-presence-510022-p7` (`693193037198`,
`oconnordev-tools`), manual WIF pool/provider and bootstrap account, two Browser
memberships, and native project WIF Viewer/manual-account SA Viewer memberships.
The native Spacelift stack/integration is owned by `infra/spacelift`, protected,
autodeploy-disabled, and independent of AWS integrations. Incomplete manual WIF
is preserved, not activated. Gmail OAuth/MCP remains separately managed.

All eight managed objects have `prevent_destroy`; project/pool/provider/account
use ABANDON. No authoritative IAM, API enablement, billing, networks, keys or
impersonation is managed. Native SA Viewer includes account key-metadata reads,
not key material, signing or token minting.

Use the [operations runbook](../../docs/runbooks/gcp-google-auth-discovery.md)
for exact identities, narrow scope and owner-only real-plan gates. Configuration
and offline tests do not prove live state reconciliation. `mise run test:opentofu-gcp`
uses isolated mock configuration without import blocks; its mock creates are not
live plan evidence. Preserve imports and provider locks; keep secrets/inventory
dumps outside Git.
