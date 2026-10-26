# Google Auth project operations

## Ownership and identity

Administrative `infra/spacelift` owns protected, autodeploy-disabled
`oconnordev-gcp-google-auth` and its native GCP integration outside AWS loops.
Root `infra/gcp/google-auth` declares project `adept-presence-510022-p7`, number
`693193037198`, name `oconnordev-tools`. Native authentication uses
`GOOGLE_OAUTH_ACCESS_TOKEN`, not a key, credentials mount, manual WIF JSON or
`GOOGLE_APPLICATION_CREDENTIALS`. Cloud-platform scope is not an IAM grant.
Gmail OAuth/MCP remains manually managed and outside this root.

The manual WIF pool/provider are both `spacelift`, display names **Spacelift**
and **spacelift** respectively. Issuer is `https://andrewoconnor.app.spacelift.io`,
audience `andrewoconnor.app.spacelift.io`, mapping `google.subject = assertion.sub`
and `attribute.stack = assertion.callerId`; condition is exactly
`assertion.callerType == 'stack' && assertion.callerId == 'oconnordev-gcp-google-auth'`.
The manual account is
`spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com`, with no
configured display name or description. The manual WIF setup is incomplete;
its presence does not prove impersonation works and is not an auth-repair task.

## Managed scope and preservation

Eight objects are declared: project, pool, provider, manual service account,
Browser memberships for manual and native accounts, project WIF Viewer for
native, and SA Viewer for native scoped only to the manual account.
Native identity is
`gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com`.
IAM memberships are additive, unconditional single-member resources. Never
replace an authoritative policy, clear unrelated members or introduce Owner,
Editor, impersonation or Service Usage Viewer to silence a read failure.

SA Viewer includes getIamPolicy and key-metadata get/list, not key creation,
signing, token minting or key material retrieval. Project Browser supplies project
IAM-policy reads. No APIs, billing association, network, OAuth clients or
service-account keys are managed. The service-account oauth2ClientId is not an
ordinary Gmail OAuth client ID. Absent labels/parent/billing account or metadata
must not be guessed into configuration; inspect actual plan values and stop on drift.

Google provider **8.8.1** is lockfile-pinned. All eight objects have
`prevent_destroy`; project, pool/provider and service account use ABANDON.
This is state relinquishment behavior, not permission to remove configuration.
Provider attribution/default labels are disabled/empty. `auto_create_network`
is a narrowly ignored creation-only field: do not set it false to satisfy a
scanner, since creation can enable Compute and remove the default network.
Existing project Checkov exceptions describe preservation scope, not hardening.

## Owner plan gates

Use the existing native stack, exact reviewed revision and refreshed saved-plan
JSON. Import identities are explicit in `imports.tf`; existing state addresses
must resolve to the same objects. No guessed import IDs or missing-read defaults.

```sh
python3 scripts/ci/verify_gcp_discovery_plan.py \
  --plan-json /path/to/actual-proposed-plan.json --expected-imports 0
```

An owner-reviewed reconciliation of the two existing native read memberships
may use `--expected-imports 2` only after verifying those exact grants and every
other managed object is a no-op. This is an unresolved live-plan gate, not a
claim of completed state reconciliation. For steady state require zero imports,
adds, changes and destroys, no unknown/deferred/incomplete plan, failed checks
or non-no-op resource drift. Keep exact address/identity checks and import blocks.
Account IAM import IDs require full `projects/PROJECT/serviceAccounts/EMAIL`,
then space-separated role/member; project IAM uses project ID. Pool/provider
import paths use project ID while computed names use project number.

Stop on permissions/API errors; do not broaden IAM or enable services. Only the
owner approves/applies. After apply require a fresh zero-import/no-change plan.
Never remove resources and apply as rollback; state-only relinquishment needs
separate review, backups and identity readback with protections retained.

## Local checks and limits

```sh
mise run test:opentofu-gcp
mise run test:python
mise run validate
```

The offline fixture copies actual configuration/lock except imports, which mock
providers cannot execute. Eight mock creates prove configuration, not a live
import/no-change plan. No credentials or inventory dumps belong in this repository.
Google 8.8.1 does not manage ordinary Google Auth Platform consent/Audience/Data
Access or Gmail OAuth-client settings; `google_iam_oauth_client` is Workforce
Identity Federation, not that product. Do not invent resources or new consent.

References: [native GCP integration](https://docs.spacelift.io/integrations/cloud-providers/gcp),
[project IAM import](https://github.com/hashicorp/terraform-provider-google/blob/v8.8.1/website/docs/r/google_project_iam.html.markdown),
[service-account IAM import](https://github.com/hashicorp/terraform-provider-google/blob/v8.8.1/website/docs/r/google_service_account_iam.html.markdown).
