# Native GCP project discovery (stage one)

## Ownership and boundaries

This PR is discovery, **not project adoption or a completed import**. The
administrative `oconnordev` stack (`infra/spacelift`) owns the standalone
`oconnordev-gcp-google-auth` stack and its `spacelift_gcp_service_account`.
The discovery root is `infra/gcp/google-auth`. It contains only a
`google_project` data source and identity outputs, no managed Google resources,
IAM resources or import blocks. Both stacks have autodeploy disabled and
Spacelift deletion protection. The GCP stack is outside the AWS
`local.managed_stacks` loop: no AWS integration or account-map globs attach to it.

The owner authorizes merge/apply. Hermes may publish a draft through the existing
gateway, but does not merge, apply, grant Google IAM, or import state. Google IAM
bootstrap is user-operated in Cloud Shell under the user's own identity.

Use native Spacelift GCP integration on the existing free account, not generic
paid OIDC. Native integration creates a Spacelift-managed, per-stack service
account and injects temporary `GOOGLE_OAUTH_ACCESS_TOKEN` credentials into runs.
Only `https://www.googleapis.com/auth/cloud-platform` is requested. **That scope
is not a permission and does not make a token read-only**: project Google IAM
bindings enforce the read boundary. Native integration availability and token
issuance on this particular account remain live gates, not locally proven facts.
No paid upgrade, service-account key, hosted OIDC pool, new WIF provider or
compiler installation is required by this path.

## Expected project and evidence boundary

User-reported `gcloud projects describe` metadata (not authenticated from this
checkout):

| Field | Expected |
| --- | --- |
| Project ID | `adept-presence-510022-p7` |
| Project number | `693193037198` |
| Display name | `oconnordev-tools` |
| Lifecycle state | `ACTIVE` |
| Labels | None reported |
| Organization/folder parent | None reported |
| Billing association | **Unknown; do not infer unbilled** |

Postconditions reject mismatched ID, number or name. Google provider 8.7.0
exposes no `lifecycle_state` data-source attribute: its real project read rejects
non-ACTIVE projects. Mock tests cannot prove ACTIVE status, real permissions,
token issuance, billing visibility or native account entitlement.

Google 8.7.0 is pinned exactly, verified against its stable upstream v8.7.0
release (not a beta provider). Its new lock uses the OpenTofu registry and signed
checksums for Linux amd64 and Darwin amd64/arm64. Existing provider pins and locks
are unchanged. The installed Spacelift 1.55.0 schema confirms the native
resource's required `token_scopes` set, `stack_id`, and computed string
`service_account_email`; the administrative output is
`gcp_google_auth_service_account_email`.

## Stage one: owner bootstrap and proposed-run proof

1. Review the draft and exact-head CI. Owner merges only after review. Run the
   administrative stack plan. Expected isolated delta: **2 adds** (standalone
   stack and native service account), **0 changes, 0 destroys**, plus the new
   email output. This is a prediction, not a live plan result. Stop for any
   unrelated drift, unsupported native resource/entitlement or unexpected count.
2. Owner approves administrative apply. Capture the actual
   `gcp_google_auth_service_account_email` output from the `oconnordev` stack.
   Verify it matches the native integration displayed on
   `oconnordev-gcp-google-auth`; never invent an email from the stack ID. Creation
   of this native service account is in Spacelift's project, not a project import
   or an IAM grant in the target project.
3. In Cloud Shell, as the project administrator, run the following. The prompt
   is for the non-secret email captured above. This command **writes one
   project-scoped IAM binding**; it neither changes project metadata nor billing.

   ```sh
   PROJECT_ID='adept-presence-510022-p7'
   read -r -p 'Paste administrative gcp_google_auth_service_account_email output: ' SPACELIFT_GCP_EMAIL
   test -n "$SPACELIFT_GCP_EMAIL" || exit 1
   gcloud projects describe "$PROJECT_ID" --format=json
   gcloud projects add-iam-policy-binding "$PROJECT_ID" \
     --member="serviceAccount:${SPACELIFT_GCP_EMAIL}" \
     --role='roles/browser' --condition=None
   gcloud projects get-iam-policy "$PROJECT_ID" \
     --flatten='bindings[].members' \
     --filter="bindings.role:roles/browser AND bindings.members:serviceAccount:${SPACELIFT_GCP_EMAIL}" \
     --format='table(bindings.role,bindings.members)'
   ```

   Compare the project ID, number, name, ACTIVE status, labels and parent before
   granting. Stop on mismatch. Inspect all existing direct/inherited grants on
   this native identity so additional roles cannot invalidate the read-only
   claim. Grant **no Owner/Editor**, billing write, service enablement or broad
   organization role. `roles/browser` is metadata discovery, not general resource
   inventory. Allow IAM propagation before retrying a proposed run.
4. Ensure the GCP stack has no `GOOGLE_APPLICATION_CREDENTIALS`, credentials
   mount or overriding Google credentials. The existing local federation JSON
   is **not** mounted or reused; it belongs to the prior manual WIF path, which
   remains intact. Do not print `GOOGLE_OAUTH_ACCESS_TOKEN`, dump environment
   variables, or enable token-bearing debug logs. The Google provider consumes
   Spacelift's injected token directly; configuration contains no token.
5. Trigger a **proposed run** for `oconnordev-gcp-google-auth` after the grant.
   Review logs and outputs for the exact identity and a successful data-source
   read with **0 managed-resource adds/changes/destroys and no imports**. Output
   additions alone are expected; the stack has no cloud writes to approve.
   Record run ID, commit, principal email and redacted identity output. A local
   mock plan is not a substitute. If native token creation or read fails, stop
   and diagnose the exact operation rather than buying OIDC or granting writes.

The Google project data source also calls Cloud Billing `projects.getBillingInfo`.
The documented permission for this API is `resourcemanager.projects.get`,
consistent with metadata-only discovery, not a reason to grant billing writes.
It can fail for visibility/API restrictions; the provider tolerates an
API-not-enabled error, so a successful project read alone does **not** establish
billing association. Do not silently enable services or broaden IAM. Review any
additional proven read-only requirement with the owner first.

## Stage two: separate preservation-only import PR, blocked for now

Do not add `google_project` resources or imports until all these gates hold:

- Native account creation and issued run token are proven on this account.
- Google IAM access and exact project identity are proven by the proposed run.
- Owner obtains current parent, labels and billing association (including a
  confirmed absence, if applicable). From Cloud Shell the owner can read
  `gcloud billing projects describe adept-presence-510022-p7 --format=json`;
  record the response or explicit visibility failure, not an inferred value.
- Relevant Google/billing read permissions are demonstrated by actual provider
  operations. No billing modification permissions are granted by default.
- The later resource preserves the observed metadata and billing association,
  uses `lifecycle { prevent_destroy = true }` and explicit
  `deletion_policy = "PREVENT"` supported by the pinned provider. Never use an
  obsolete deletion field, `auto_create_network = false`, new labels, parent
  migration or billing unlink as an adoption shortcut.
- A separate owner-reviewed PR contains one declarative import of project ID
  `adept-presence-510022-p7`. Its live plan must show **1 import, 0 adds,
  0 changes, 0 destroys**. Any difference blocks approval. Owner alone approves
  the import apply; repeat the no-change plan afterward.

Project adoption does not adopt the Google Auth Platform consent screen,
ordinary OAuth client, client secret, OAuth scopes, redirects or agentic flags.
`google_iam_oauth_client` is not the ordinary Gmail OAuth client. Existing custom
Gmail read-only MCP, its credentials and scopes remain untouched. Existing
manually created WIF pools/providers/service accounts/bindings remain untouched;
no deletion or migration of them is included.

## Verification and rollback

Offline checks: `mise run test:opentofu-gcp` (exact identity success, mismatched
number/name rejected), focused Python contracts in `test_gcp_discovery.py`, the
real mock-plan JSON no-change/import gate `verify_gcp_discovery_plan.py`, and
`mise run test`, `mise run validate`, `mise run fmt`, `mise run lint`, and
`mise run workflow-lint`. Initialization/validation use
`-backend=false -lockfile=readonly`; no live Google or Spacelift credentials are
needed. Only this root introduces a Google provider lock. These checks do not
establish any live bootstrap or project import.

If bootstrap must be abandoned, leave autodeploy disabled. The owner can remove
only the newly granted `roles/browser` member binding using
`gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SPACELIFT_GCP_EMAIL}" --role='roles/browser' --condition=None`
and verify IAM readback. Do not replace the entire policy or delete the project,
existing OAuth client, or manual WIF resources. Stack/native integration removal
requires a separate owner-reviewed administrative plan and intentional handling
of Spacelift deletion protection, never an unattended destroy.

## Primary sources

- [Native GCP integration](https://docs.spacelift.io/integrations/cloud-providers/gcp)
- [Billing project read permission and token scope](https://cloud.google.com/billing/docs/reference/rest/v1/projects/getBillingInfo)
- [Stable Google v8.7.0](https://github.com/hashicorp/terraform-provider-google/releases/tag/v8.7.0)
- [Pinned project data-source implementation and ACTIVE rejection](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/resourcemanager/data_source_google_project.go)
- [Pinned project read, billing read and deletion policy](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/resourcemanager/resource_google_project.go)
- [Project resource/import documentation](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/website/docs/r/google_project.html.markdown)
