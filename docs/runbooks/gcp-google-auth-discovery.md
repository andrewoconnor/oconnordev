# Native GCP project discovery and preservation-only adoption

## Ownership and boundaries

`infra/spacelift` (administrative `oconnordev` stack) owns the separate native
`oconnordev-gcp-google-auth` stack and Spacelift-managed service account.
The stack stays outside AWS `local.managed_stacks` and integration loops.
Both stacks disable autodeploy and have Spacelift deletion protection.

Stage-two code in `infra/gcp/google-auth` adds exactly one `google_project`
resource and one declarative import. Independent project discovery remains.
**This is not a completed import or a claim of an executed stage-two plan.**
Only the owner approves merge/apply. Hermes may prepare a draft, but does not
apply, import state locally, change Google IAM or publish without authorization.
No OAuth client/consent screen, secrets, Gmail MCP/scopes, manual WIF resources,
APIs, billing association or networks are adopted or modified here.

## Evidence carried forward from stage one

The preceding native run `01M4XYWS3DPJ5B2ZFPSXCG4FMV` FINISHED with exact
outputs below. This is supplied prior live evidence, not a new local cloud read.
It demonstrates native integration/token issuance and project discovery on the
existing free Spacelift account; paid generic OIDC is not needed.

| Field | Observation and source |
| --- | --- |
| Project ID | `adept-presence-510022-p7`, native run and owner Cloud Shell |
| Project number | `693193037198`, native run and owner Cloud Shell |
| Display name | `oconnordev-tools`, native run and owner Cloud Shell |
| Lifecycle | `ACTIVE`, owner `gcloud projects describe` |
| Labels | None, owner project describe |
| Organization/folder parent | None, owner project describe |
| Billing | `billingEnabled: false`, owner billing describe; `billingAccountName` omitted |

Billing is **known disabled from the owner's supplied read**, not unknown and
not a request to attach billing. The omitted account name supplies no account ID
to configure. This does not prove universal billing visibility or that future
provider billing reads can never fail. Do not infer billing from an empty
data-source field alone: the provider tolerates API-not-enabled responses.

The native integration injects `GOOGLE_OAUTH_ACCESS_TOKEN`; no credentials mount,
service-account key, `GOOGLE_APPLICATION_CREDENTIALS` or manual WIF JSON is
used. Do not print tokens/environment or enable token-bearing debug logs.
Cloud-platform is a token scope, not an IAM grant. Existing project
`roles/browser` is the metadata read boundary, not broad resource inventory.
No new IAM roles, Owner/Editor, billing writes or API enablement are required by
state adoption. Any read failure must be diagnosed and owner-reviewed, not
worked around with elevated permissions.

## Pinned-provider preservation behavior

Google provider **8.7.0** and all existing locks remain unchanged. Its installed
schema and pinned source support `deletion_policy = "ABANDON"`. Together with
`lifecycle { prevent_destroy = true }`, this blocks configured destroys and
makes provider-level removal forget state rather than delete the Google project.
This is not permission to remove the configuration or state casually.

The provider's resource read defaults deletion policy to PREVENT unless the
provider default is supplied. Set ABANDON explicitly on both resource and
provider so import read does not produce a PREVENT-to-ABANDON update. These are
client/state policies, not Google metadata writes. Do not accept a plan update
merely because it appears client-side: the adoption gate requires zero changes.

`auto_create_network` defaults true; the importer sets true without inspecting
the current default network. False is dangerous on project creation: the
provider enables Compute and deletes the default network/firewalls. This root
omits that setting and narrowly ignores **only** `auto_create_network`, a
creation-only flag, not a network inventory assertion. Current default-network
existence is unknown; no network is managed, created or deleted by import/read.
The live gate rejects project creation regardless of this default.

Provider attribution labels default true in the pinned source; explicitly set
`add_terraform_attribution_label = false` and `default_labels = {}`. Do not add
labels. Billing account, organization and folder settings remain omitted; no
parent migration, billing link/unlink, or broad lifecycle ignore is introduced.
A live difference in these fields blocks adoption, not an invitation to update.

The independent data source rejects non-ACTIVE reads and ID/number/name mismatch.
A resource precondition depends on those exact reads, preventing configured name
from masking actual name drift. Resource postconditions and outputs verify the
same identity after adoption. Provider resource import normalizes state ID to
`projects/adept-presence-510022-p7`; the declarative import ID is the exact
project ID, **not** its numeric identifier.

Both data and managed-resource reads call Resource Manager projects.get and
Cloud Billing projects.getBillingInfo. The documented billing read permission
is `resourcemanager.projects.get`, consistent with `roles/browser` and the prior
successful metadata read. The stage-two resource path still needs real proposed
run proof; do not claim broad billing permissions from stage-one success.

## Stage two: owner-reviewed live gate

1. Review the draft, independent review and exact-head CI. Keep autodeploy off.
   Obtain a **real Spacelift proposed plan** on the stage-two head using the
   existing native integration. Local mock fixtures are not acceptable evidence.
2. Require **1 import, 0 adds, 0 changes, 0 destroys**, no resource drift, only
   `google_project.google_auth` imported with ID `adept-presence-510022-p7`.
   Identity must be exactly the ID/number/name above. No IAM, billing, labels,
   parent, API or network deltas may be accepted. Stop on any discrepancy,
   incomplete checks, permission failure, changed billing/parent/labels or count.
3. Obtain the saved plan's actual `tofu show -json` output through the approved
   Spacelift workflow and run the read-only gate from the repository root:

   ```sh
   python3 scripts/ci/verify_gcp_discovery_plan.py \
     --plan-json /path/to/actual-proposed-plan.json --expected-imports 1
   ```

   The gate validates configuration addresses, every resource change/import,
   exact import ID and known identity, rejects create/update/delete/replacement,
   failed/unknown checks and non-no-op `resource_drift`. The original stage-one
   data-only `verify_plan` utility remains for historical discovery unit tests.
   Record real run ID, exact head, identity and counts. Never manufacture JSON
   or report a synthetic import count as a provider result.
4. Only the owner approves the reviewed import apply. This adopts project state,
   not cloud-write permissions. After apply, owner obtains another real plan
   requiring **0 imports, 0 adds, 0 changes, 0 destroys**, using the same gate
   with `--expected-imports 0`, and verifies identity outputs. Keep the import
   block as declarative history; it is idempotent once state is adopted.

No stage-two live plan/apply has been executed from this checkout. There are no
local Google credentials; draft publication and real proposed-run proof are
separate delivery gates, not replaced by offline tests.

## Offline verification

Run `mise run test:opentofu-gcp` for production-configuration identity tests.
OpenTofu 1.13.1's testing provider cannot perform imports (direct testing of the
importing root crashes). The runner copies the actual configuration and lock to
an isolated temporary fixture, omits **only `imports.tf`**, and runs real mock
provider tests. Managed-resource mocks are separate from data-source mocks;
wrong discovered number/name and wrong managed number must fail. The fixture
plans a **mock creation**, not a no-change/import plan, and says so explicitly.
Synthetic import JSON exists only in clearly labeled Python unit fixtures.
It is never generated as live-plan evidence.

Run `mise run test`, `mise run validate`, `mise run fmt`, `mise run lint`,
`mise run lint:python`, and `mise run workflow-lint`. Initialization/validation
use `-backend=false -lockfile=readonly`; no cloud credentials are needed.
Python contracts verify deletion/network protections and plan gates reject
mutations, wrong imports and drift. These checks establish neither a successful
live stage-two import nor new billing/IAM visibility.

## Rollback and stop conditions

Before import apply, stop/revert the draft if preservation is not exact; no state
or Google change has occurred. After adoption, do not blindly remove the resource
or destroy the stack. Have the owner review state-only detachment separately,
back up state and verify the project remains ACTIVE with unchanged identity.
ABANDON is a fail-safe, not an automated rollback procedure. Keep project and
Spacelift deletion protection intact. No IAM rollback, OAuth migration or manual
WIF cleanup is part of this stage.

## Primary sources

- [Native GCP integration](https://docs.spacelift.io/integrations/cloud-providers/gcp)
- [Billing read permission/scope](https://cloud.google.com/billing/docs/reference/rest/v1/projects/getBillingInfo)
- [Pinned project resource/import/deletion/network implementation](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/resourcemanager/resource_google_project.go)
- [Pinned provider attribution-label and deletion-policy defaults](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/provider/provider.go)
- [Pinned data-source implementation and ACTIVE rejection](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/google/services/resourcemanager/data_source_google_project.go)
- [Project resource/import documentation](https://github.com/hashicorp/terraform-provider-google/blob/v8.7.0/website/docs/r/google_project.html.markdown)
