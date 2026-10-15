# Native GCP discovery and preservation-only read-access adoption

## Ownership and scope

`infra/spacelift` (administrative `oconnordev` stack) owns the protected,
autodeploy-disabled `oconnordev-gcp-google-auth` stack and native Spacelift-managed
service account, outside AWS integration loops. Neither is cloud-imported here.
Native auth continues using `GOOGLE_OAUTH_ACCESS_TOKEN`: no key, credentials
mount, manual WIF JSON or `GOOGLE_APPLICATION_CREDENTIALS`. Cloud-platform is a
token scope, not an IAM grant. Existing Gmail OAuth/MCP stays unchanged.

The project was already adopted. Keep its import block as idempotent history:
**zero project imports** this stage. The five bootstrap objects below were
already adopted in supplied FINISHED run `01M4ZV628AS0TYRQGFDKEWDF55`:

| Address | Existing identity |
| --- | --- |
| `google_iam_workload_identity_pool.spacelift` | Pool `spacelift` in project `adept-presence-510022-p7` |
| `google_iam_workload_identity_pool_provider.spacelift` | Provider `spacelift` in that pool |
| `google_service_account.bootstrap` | `spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com` |
| `google_project_iam_member.browser_manual` | Manual account above, `roles/browser` |
| `google_project_iam_member.browser_native` | `gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com`, `roles/browser` |

Exact import IDs are in `infra/gcp/google-auth/imports.tf`. Pool/provider importer
paths use project **ID** to preserve their configured project field; computed
resource names use project **number**. Member import IDs use space-separated
project ID, role and `serviceAccount:EMAIL`.

Only additive single-member IAM resources are declared. No authoritative project
or service-account policy/binding, API resources or impersonation grant. Preserve
the owner's policy and unrelated members; never clear a policy. Stage three
adopts only the two owner-granted existing read memberships below;
the five bootstrap imports and project import must remain no-op history.

## Supplied owner evidence, not a new local cloud read

The mandatory private inventory attachment was read; its source dump, owner
email and etags are deliberately not committed. It shows:

- Project ID `adept-presence-510022-p7`, number `693193037198`, name
  `oconnordev-tools`, ACTIVE. Prior owner evidence has no labels or parent and
  `billingEnabled: false`, billingAccountName omitted. Do not link billing.
- Pool `spacelift`, display name **Spacelift**, ACTIVE, no description returned.
- Provider `spacelift`, display name **spacelift**, ACTIVE. Issuer
  `https://andrewoconnor.app.spacelift.io`, audience `andrewoconnor.app.spacelift.io`.
  Mapping exactly `google.subject = assertion.sub` and
  `attribute.stack = assertion.callerId`; condition exactly
  `assertion.callerType == 'stack' && assertion.callerId == 'oconnordev-gcp-google-auth'`.
- Manual `spacelift-google-auth` account has **no displayName** (unlike earlier
  intended bootstrap settings), no description and **no IAM bindings**. Preserve
  absence; do not add a name or `roles/iam.workloadIdentityUser` binding.
- `109396950295423788712` is the manual account's unique ID and reported
  service-account oauth2ClientId, **not an ordinary Gmail OAuth client ID**.
- Project `roles/browser` contains exactly the manual and native accounts above;
  the existing owner binding is outside managed scope.
- `iam.googleapis.com`, `iamcredentials.googleapis.com`, `sts.googleapis.com`
  and `cloudresourcemanager.googleapis.com` are **all absent from the supplied
  enabled-services list**. Do not enable/import them or declare
  `google_project_service`. This bounded observation does not prove that every
  API request must fail.

This is an incomplete/unused manual WIF bootstrap, **not an auth repair** or
proof WIF impersonation works. Native auth already worked: supplied preceding
run `01M4XYWS3DPJ5B2ZFPSXCG4FMV` FINISHED with exact project identity. That
proves neither permission for new WIF/SA reads nor successful bootstrap adoption.

## Stage-three existing read memberships

The owner reports both grants succeeded. This is supplied evidence, not a new
local policy read. Adopt exactly these unconditional memberships for native
`gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com`:

| Address | Role | Scope |
| --- | --- | --- |
| `google_project_iam_member.wif_viewer_native` | `roles/iam.workloadIdentityPoolViewer` | Project `adept-presence-510022-p7` |
| `google_service_account_iam_member.viewer_native` | `roles/iam.serviceAccountViewer` | Only `projects/adept-presence-510022-p7/serviceAccounts/spacelift-google-auth@adept-presence-510022-p7.iam.gserviceaccount.com` |

Native `roles/browser` includes `resourcemanager.projects.getIamPolicy` for
project member reads. SA Viewer includes `iam.serviceAccounts.getIamPolicy` for
the account-scoped IAM member read, so no additional read grant is needed.
Do not request Owner, Editor, impersonation permissions or Service Usage Viewer:
there are no API resources in this adoption.

These historical generated commands were **not executed by this checkout**;
the owner reports running them successfully. Do not rerun them for adoption. They are
explicit IAM writes for the owner to review/run in their authenticated Cloud
Shell, not an automatic prerequisite repair. They add a project-scoped WIF
reader and a reader on **only the manual account**; no policies are replaced.

```sh
PROJECT_ID='adept-presence-510022-p7'
MANUAL_SA="spacelift-google-auth@${PROJECT_ID}.iam.gserviceaccount.com"
NATIVE_SA='gcp-01m4xs8mrej8cdgz286edc0ab2@spacelift.iam.gserviceaccount.com'
MEMBER="serviceAccount:${NATIVE_SA}"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="$MEMBER" --role=roles/iam.workloadIdentityPoolViewer --condition=None

gcloud iam service-accounts add-iam-policy-binding "$MANUAL_SA" \
  --project="$PROJECT_ID" --member="$MEMBER" \
  --role=roles/iam.serviceAccountViewer --condition=None
```

WIF viewer covers pool/provider get. The pinned service-account resource read
requires `iam.serviceAccounts.get`. The predefined SA Viewer role additionally
bundles getIamPolicy and **key-metadata reads** (`iam.serviceAccountKeys.get`
and `iam.serviceAccountKeys.list`), scoped here to only the manual account.
Key-metadata get/list is additional disclosure, not key material retrieval.
Those key-metadata reads are not required for adoption. The role grants no
key creation, signing, token minting or impersonation. Review this bundled
access before granting; replacing it with a custom role is a separate review
that must retain both metadata get and account getIamPolicy for this configuration.
Read back the exact project/account policies and verify scope after granting.
The two non-secret bindings are the only new imports in this stage. Retry via native
integration; stop on unexpected denials/API errors. Do not enable services or
broaden grants to silence provider failures.

## Pinned-provider preservation

Google **8.7.0**, OpenTofu **1.13.1** and all nine root lockfiles stay unchanged.
Installed schema and tagged source were inspected: pool, provider and service
account support `deletion_policy = "ABANDON"`; their import/read default uses
provider deletion policy if set, otherwise DELETE. Project read otherwise defaults
PREVENT. Explicit ABANDON on provider and those resources avoids client-policy
updates at import. All eight managed objects have `prevent_destroy = true`; IAM
members have no deletion_policy field. ABANDON forgets state rather than deleting
cloud objects; it is not authorization to remove configuration/state casually.

ACTIVE pool/provider omit disabled in owner JSON: preserve false. Missing
descriptions read as empty strings. The manual SA's omitted disabled is false;
absent displayName/description read as empty strings, so omit them. Do not invent
metadata or ignore drift. A different live plan blocks adoption.

Existing project protections remain: independent discovery, exact identity
pre/postconditions, provider attribution labels disabled/default labels empty,
billing/parent/labels omitted, narrowly ignored creation-only
`auto_create_network`. Never set it false to satisfy a scanner: creation would
enable Compute and delete the default network. Default-network existence and
audit configuration remain unknown; the two existing project-local Checkov skips
explain preservation scope, not hardening guarantees. No new security skips are
needed for these bootstrap resources (checked with the pinned scanner).

Project data/resource reads use projects.get and projects.getBillingInfo; the
billing read permission is `resourcemanager.projects.get`, within roles/browser.
Omitted billingAccountName supplies no account ID to configure and is not proof
of universal billing visibility. An empty provider billing field alone does not
prove billing disabled: API-not-enabled is tolerated by the provider.

## Real-plan gates and owner apply

1. Keep autodeploy off. Owner reports successful grants and the five-bootstrap
   apply above. Exact-head CI and a **real native Spacelift proposed plan for
   the two read memberships** remain pending until this tree is published. No invented local
   credentials, generated plan JSON or synthetic totals substitute for it.
2. Require **2 imports, 0 adds, 0 changes, 0 destroys**, only the two read members
   above, with all six previously managed objects no-op, exact identity/trust
   and no drift. Require eight managed objects plus existing project discovery
   data; never re-import the five bootstrap objects or the project. Stop on read denial,
   failed/unknown checks, unexpected API request, metadata drift or any delta.
3. Obtain actual saved-plan `tofu show -json` through the approved workflow:

   ```sh
   python3 scripts/ci/verify_gcp_discovery_plan.py \
     --plan-json /path/to/actual-proposed-plan.json --expected-imports 2
   ```

   The gate checks exact configuration/change/import sets; known project,
   pool/provider names and ACTIVE state; display names; issuer, audience, mapping,
   stack condition; manual SA identity/absent metadata; unconditional browser
   members. It rejects other addresses, all create/update/replace/delete actions,
   duplicate/missing/wrong imports, unknown values, deferred/incomplete/errored
   plans, failed/unknown checks and non-no-op resource drift. Record real run ID,
   exact head and actual totals. The project-only unit utility is historical;
   the CLI defaults to stage-three read access with only **2 or 0** imports.
   `--mode bootstrap --expected-imports 5` is only for historical stage-two
   evidence, not this expanded configuration. Both read memberships must have
   the exact native principal, role and scope with no IAM condition. Account
   member import IDs require the full `projects/PROJECT/serviceAccounts/EMAIL`
   prefix, followed by space-separated role and member; project IAM uses project ID.
4. Only the owner approves merge/apply after fresh tracked-plan review. Require
   a subsequent real plan with **0 imports, 0 adds, 0 changes, 0 destroys**, same
   gate with `--expected-imports 0`. Keep all imports as idempotent history.

No live read-access import plan or apply has run from this checkout. The supplied
bootstrap FINISHED run does not prove this stage's two-import plan. There are no
local Google credentials. Publication, exact-head real plan proof and owner apply
approval are separate gates, not replaced by offline tests.

## Offline verification, rollback and OAuth boundary

`mise run test:opentofu-gcp` copies actual config/lock to an isolated fixture and
omits **only `imports.tf`**, containing old and new imports. OpenTofu 1.13.1
mocks panic on imports. The fixture plans eight **mock creates**, not a live
import/no-change plan. Synthetic plan JSON exists only in labeled unit tests.
Run `mise run test`, `mise run validate`, `mise run fmt`, `mise run lint`,
`mise run lint:python`, `mise run workflow-lint`, and `mise run checkov`.
Initialization uses `-backend=false -lockfile=readonly`; no cloud writes needed.

Before apply, stop/revert if preservation is not exact. After adoption do not
remove resources or destroy the stack: owner-reviewed state-only detachment,
backups and identity readback are separate operations. Keep project/stack
deletion protection. No WIF cleanup, policy clearing or unrelated IAM rollback.

Google 8.7.0 does not support ordinary Google Auth Platform consent, Audience,
Data Access, agentic settings or Gmail OAuth-client adoption. Its
`google_iam_oauth_client` is Workforce Identity Federation, not that product.
Do not add fake resources/imports, collect secrets, rotate auth or request a new
user authorization flow. Later owner-supplied **non-secret** manual inventory
may record client type, audience/publishing status, scopes and redirect URIs;
that remains manual scope, and secrets stay outside repository/state.

## Primary sources

- [Native GCP integration](https://docs.spacelift.io/integrations/cloud-providers/gcp)
- [Pinned pool implementation](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/iambeta/resource_iam_workload_identity_pool.go)
- [Pinned provider implementation](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/iambeta/resource_iam_workload_identity_pool_provider.go)
- [Pinned service-account implementation](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/resourcemanager/resource_google_service_account.go)
- [Pinned project/import behavior](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/resourcemanager/resource_google_project.go)
- [Pinned project IAM member import format](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/website/docs/r/google_project_iam.html.markdown)
- [Pinned service-account IAM import format and read](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/website/docs/r/google_service_account_iam.html.markdown)
- [Pinned service-account IAM implementation](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/resourcemanager/iam_service_account.go)
- [Pinned provider defaults](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/provider/provider.go)
