# GitHub settings: preservation-only adoption

## Scope and evidence

Root: `infra/github/oconnordev`; existing Spacelift stack:
`oconnordev-github-repository-config`. This is declarative adoption configuration,
**not a performed state import or proof of a live zero-change plan**.

The [sanitized inventory](../assets/github-settings-observed.json) records the
capture timestamp and source coverage. Authenticated native MCP reads confirmed
one repository ruleset, its full detail with explicit empty bypass actors, eight
labels (reported total eight), and only the inherent owner as collaborator.
Unauthenticated public REST reads separately confirmed `default_branch = master`
and the complete empty topics list. This is not full repository administration
coverage. The [read prerequisite](github-settings-read.md) remains partial.

`settings-adoption.tf` uses literals verified against that capture, not live data
sources or configuration generated from unknown defaults. It adds 11 import
instances through four import blocks:

| Resource address | Provider import ID |
| --- | --- |
| `github_repository_ruleset.master` | `oconnordev:24274432` |
| `github_issue_label.observed["bug"]` | `oconnordev:bug` |
| `github_issue_label.observed["duplicate"]` | `oconnordev:duplicate` |
| `github_issue_label.observed["enhancement"]` | `oconnordev:enhancement` |
| `github_issue_label.observed["good first issue"]` | `oconnordev:good first issue` |
| `github_issue_label.observed["help wanted"]` | `oconnordev:help wanted` |
| `github_issue_label.observed["invalid"]` | `oconnordev:invalid` |
| `github_issue_label.observed["question"]` | `oconnordev:question` |
| `github_issue_label.observed["wontfix"]` | `oconnordev:wontfix` |
| `github_branch_default.observed` | `oconnordev` |
| `github_repository_topics.observed` | `oconnordev` |

The label map retains exact names, six-character colors, and descriptions.
Singular `github_issue_label` resources do not delete unlisted labels. The topics
resource owns **only the topics set**: the observed empty array is known, not a
substitute for an omitted field. Stop if refreshed topics differ; do not change a
newly added topic as part of adoption. Pinned provider v6.13.0 skips
`ReplaceAllTopics` when the configured set is empty, so a later nonempty-to-empty
update cannot reliably clear topics and may leave persistent drift. This adoption
of an already-empty set is safe only with the zero-update plan gate; clearing
future topics needs a separately reviewed provider fix or supported update path.
The default branch remains `master`,
with `rename = false` and `wait_for_rename = false`.

The ruleset retains `name = master`, branch target, active enforcement,
`include = ["~DEFAULT_BRANCH"]`, `exclude = []`, deletion/non-fast-forward rules,
and the pull-request rule with **`allowed_merge_methods = ["squash"]`**. All five
observed pull-request review booleans/count values remain false/zero. No other
rules or reviewer requirements are introduced. Zero optional `bypass_actors`
blocks represent the explicit empty observed array; this provider's schema does
not accept a `bypass_actors = []` argument. Its source expansion returns an empty
slice rather than null for zero actors. No bypass permission is granted to the
provider App.

All four resource declarations have `prevent_destroy = true`. This blocks planned
destruction while the declarations remain, not updates, configuration removal,
manual deletion, or GitHub writes by another actor. Do not treat it as a plan gate.

The five Actions variables are already managed and **not imported again**. Their
resource addresses, optional DrumrollWorld counts, all input definitions, provider
authentication, and PRODUCTION/TOOLS/DRUMROLLWORLD dependency chain stay unchanged.

## Exact provider contract

The existing OpenTofu-registry lock resolves `integrations/github` **6.13.0**;
`versions.tf` and `.terraform.lock.hcl` are unchanged. No upgrade is required.
The actual locked binary's `tofu providers schema -json` capture is checked in at
`scripts/ci/tests/fixtures/github-adoption-provider-schema.json`. It includes the
four exact resource schemas and baseline hashes for untouched provider/input and
Spacelift wiring files. The schema explicitly supports the optional/computed
list `rules.pull_request.allowed_merge_methods`, which is explicitly configured.

Authoritative tagged provider docs and implementation:

- [Ruleset schema and import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/repository_ruleset.md)
- [Ruleset resource/import source](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/github/resource_github_repository_ruleset.go)
- [Merge-method expansion/flattening and empty bypass semantics](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/github/util_rules.go)
- [Singular label import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/issue_label.md)
- [Default-branch import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/branch_default.md)
- [Topics import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/repository_topics.md)

## Dedicated provider App bootstrap (user only)

Retain the dedicated App, installed only on `andrewoconnor/oconnordev`, and its
existing Spacelift context `oconnordev-github-provider-auth`. Current live App
permissions have **not** been verified. Original documentation only required
Variables read/write plus Metadata read. The user must review/approve the
following repository permissions before managing this expanded resource scope:

| Permission | Required use |
| --- | --- |
| Variables: read and write | Existing five managed Actions variables; retain |
| Metadata: read-only | Repository lookups; retain |
| Administration: read and write | Ruleset, default branch, topics |
| Issues: read and write | Singular repository labels |

GitHub endpoint permission references: [rulesets](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset),
[repository update](https://docs.github.com/en/rest/repos/repos#update-a-repository),
[topics](https://docs.github.com/en/rest/repos/repos#replace-all-repository-topics),
and [labels](https://docs.github.com/en/rest/issues/labels#create-a-label).
GitHub permissions are coarse: Administration grants capabilities outside the HCL
scope. That broader API capability needs explicit user approval; it is not granted
by this change. Approve any pending installation permission update in GitHub UI.

Keep `TF_VAR_github_app_id`, `TF_VAR_github_app_installation_id`, and the secret,
write-only `TF_VAR_github_app_private_key` in the dedicated context, attached only
to this stack. The key remains an ephemeral provider input. Never borrow the
machine-user PAT, Hermes/MCP credentials, VCS credentials, or another private key.
Do not put keys in code, plan/state, outputs, chat, or local test fixtures. Do not
broaden the read gateway; its policies and AWS provider remain unchanged.

A live plan can fail before import because the App installation/permissions have
not been approved, context values are missing, or producer inputs are unavailable.
A 401/403/404 during import/refresh is an authorization/bootstrap or missing-object
investigation, **not permission to create a replacement**. Stop and let the user
resolve the dedicated App/context; do not change authentication or skip refresh.

## Initial live plan gate and rollout

1. Refresh scoped inventory if the capture has aged; verify full rule parameters,
   explicit bypass array, label totals, default branch and topics. Unknown is not
   empty. Confirm the latest reviewed draft head is what Spacelift plans.
2. Have the user complete the dedicated App approval above; verify existing five
   state addresses and producer dependency inputs through the existing stack.
3. Review a refreshed Spacelift plan from that exact head. For a first adoption,
   require **11 imports, zero creates, zero updates, zero deletes/replacements**.
   The existing five variables must have no actions. Check every import ID/address
   against the table and inspect before/after values, especially squash-only merge
   methods and bypass actors. Already-imported instances may reduce the import
   count only when exact state addresses/objects have been verified.
4. Abort on any drift, replacement, unexpected resource, lost parameter, hidden
   read failure, new label/topic value, or changed variable. Refresh evidence and
   review a separate correction; do not use `ignore_changes`, defaults, targeting,
   `-refresh=false`, or guessed values to make adoption appear safe.
5. Only the user may approve/apply the import-only plan. Afterwards verify the 11
   exact addresses in the existing stack and a fresh no-change plan. Declarative
   import blocks may remain: they do not reimport objects already at the address.

No local `tofu import`, live plan with borrowed credentials, apply, deploy, GitHub
write, or AWS write is part of local validation. A passing offline check is not a
claim that the state import has happened.

Before import apply, rollback means reverting the new adoption HCL/import blocks;
there are no live changes to undo. After import apply, do not remove resource HCL
and apply (that could destroy managed settings); use a separately reviewed
state-only relinquishment procedure in the existing stack, preserving GitHub
objects and all five Actions variables. Never destroy a ruleset or label to undo
an import.

## Unadopted families and null/unknown semantics

- No bare `github_repository` resource: public metadata omits administration/merge
  flags and other fields. Provider defaults could change unread settings.
  Description/homepage are observed **null**, not empty strings, and stay unmanaged.
- Only the owner was listed as collaborator. This is inherent ownership, not an
  importable grant. No singular owner collaborator, authoritative collaborator
  set, invitation, grant deletion, or permission reduction is declared.
- Eight public environments are inventoried, with empty visible protection rules
  and null deployment-branch policy. Custom protection rules are not authenticated;
  public list completeness does not prove complete effective environment settings.
  They remain externally owned; null is not converted to a guessed policy block.
- Legacy branch protection, hooks, Actions policy/default token permissions,
  additional Actions variables, Pages, vulnerability alerts and automated security
  fixes are unavailable through the permitted read coverage. The recorded
  401/403/404 responses mean **unknown**, not absence.
- Secrets cannot be recovered from inventory and are externally owned. No secret
  resource/value read, workflow change, deploy key, repository-wide default, or
  AWS resource is introduced.

## Verified local results and remaining gate

With the repository-pinned tools, formatting, backend-disabled readonly-lock init,
OpenTofu validation, Ruff lint/format, and TFLint completed successfully. The full
`mise run test:python` task passed 142 tests across four suites, including four
new adoption regressions. Checkov 3.3.20 returned exit 0 with zero passed/failed/
skipped checks, zero parsing errors, and **resource_count = 0** for this GitHub
root: it provides no applicable resource security coverage here, not a security
endorsement. No scanner suppression was added.

The remaining acceptance gate is the authenticated, refreshed, exact-head live
Spacelift import-only plan after the user's dedicated App permission approval.
Local validation did not read credentials, import state, or perform an apply.

## Local verification

From the repository root with the pinned mise tools and shared provider cache:

```sh
mise exec -- tofu -chdir=infra/github/oconnordev fmt -check
mise exec -- tofu -chdir=infra/github/oconnordev init -backend=false -input=false -lockfile=readonly
mise exec -- tofu -chdir=infra/github/oconnordev validate
mise exec -- python3 -m unittest scripts/ci/tests/test_github_settings_adoption.py -v
mise exec -- ruff check scripts/ci/tests/test_github_settings_adoption.py
mise exec -- ruff format --check scripts/ci/tests/test_github_settings_adoption.py
mise exec -- tflint --chdir=infra/github/oconnordev --format=compact
mise exec -- checkov --directory infra/github/oconnordev --framework terraform
```

Tests evaluate production HCL with OpenTofu mock-provider plans and the exact
locked schema, compare observed label fields and every pull-request parameter,
reject additional rules/bypasses, reconcile import addresses/counts, and protect
untouched input/provider/wiring files. Import blocks are stripped only in temporary
offline fixtures and separately contract-tested. Those synthetic create plans
exercise configuration, **not live import behavior or a zero-change live plan**.
