# GitHub repository-settings operations

## Managed scope

Root `infra/github/oconnordev`, stack `oconnordev-github-repository-config`,
uses a dedicated provider App, not the read gateway's token. Configuration owns
one master ruleset, eight singular labels, default branch and topics, six site
Actions variables and two production environments/master branch policies.
Live state reconciliation is not established by configuration or offline tests.
The [sanitized inventory](../assets/github-settings-observed.json) is a bounded
comparison source, not a current complete administrative inventory. Refresh
scoped reads before planning. Keep missing/forbidden fields distinct from empty.

Exact settings resource identities:

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
newly added topic without separate review. Pinned provider v6.13.0 skips
`ReplaceAllTopics` when the configured set is empty, so a later nonempty-to-empty
update cannot reliably clear topics and may leave persistent drift. Managing
an already-empty set requires a zero-update plan gate; clearing
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

Site variables and environment resources are owned separately in the same
root. Preserve their state addresses and workload/TOOLS producer dependencies.
Environment IAM/bootstrap ordering is in the
[shared runbook](infrastructure-bootstrap.md#tested-artifact-environment-bootstrap).
A full-root plan can include separately reviewed environment/variable work;
that is not permission to update imported settings.

## Provider contract

The existing OpenTofu-registry lock resolves `integrations/github` **6.13.0**;
Use `versions.tf` and `.terraform.lock.hcl` as the version contract. Use the lockfile rather than floating a version.
Authoritative tagged provider docs and implementation:

- [Ruleset schema and import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/repository_ruleset.md)
- [Ruleset resource/import source](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/github/resource_github_repository_ruleset.go)
- [Merge-method expansion/flattening and empty bypass semantics](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/github/util_rules.go)
- [Singular label import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/issue_label.md)
- [Default-branch import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/branch_default.md)
- [Topics import contract](https://github.com/integrations/terraform-provider-github/blob/v6.13.0/docs/resources/repository_topics.md)

## Dedicated provider App bootstrap (user only)

Retain the dedicated App, installed only on `andrewoconnor/oconnordev`, and its
existing Spacelift context `oconnordev-github-provider-auth`. Verify effective live App permissions; only the user may approve
permission or installation changes. Required permissions:

| Permission | Required use |
| --- | --- |
| Variables: read and write | Six managed Actions variables |
| Metadata: read-only | Repository lookups; retain |
| Administration: read and write | Ruleset, default branch, topics |
| Issues: read and write | Singular repository labels |

GitHub endpoint permission references: [rulesets](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset),
[repository update](https://docs.github.com/en/rest/repos/repos#update-a-repository),
[topics](https://docs.github.com/en/rest/repos/repos#replace-all-repository-topics),
and [labels](https://docs.github.com/en/rest/issues/labels#create-a-label).
Environment management additionally requires Environments read/write.
GitHub permissions are coarse: Administration grants capabilities outside the HCL
scope. That broader API capability needs explicit user approval; it is not automatically authorized. Approve any pending installation permission update in GitHub UI.

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

## Owner reconciliation and plan gate

1. Refresh scoped inventory if the capture has aged; verify full rule parameters,
   explicit bypass array, label totals, default branch and topics. Unknown is not
   empty. Confirm the exact reviewed revision is what Spacelift plans.
2. Have the user complete the dedicated App approval above; verify existing
   state addresses and producer dependency inputs through the existing stack.
3. Review a refreshed Spacelift plan from that exact head. When all eleven settings are absent from state,
   require **11 imports, zero creates, zero updates, zero deletes/replacements**.
   The existing variables must have no actions. Check every import ID/address
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

Do not remove managed resource HCL
and apply (that could destroy managed settings); use a separately reviewed
state-only relinquishment procedure in the existing stack, preserving GitHub
objects and all Actions variables. Never destroy a ruleset or label to undo
an import.

## Unadopted families and null/unknown semantics

- No bare `github_repository` resource: public metadata omits administration/merge
  flags and other fields. Provider defaults could change unread settings.
  Description/homepage are observed **null**, not empty strings, and stay unmanaged.
- Only the owner was listed as collaborator. This is inherent ownership, not an
  importable grant. No singular owner collaborator, authoritative collaborator
  set, invitation, grant deletion, or permission reduction is declared.
- Public environments are inventoried, with empty visible protection rules
  and null deployment-branch policy. Custom protection rules are not authenticated;
  public list completeness does not prove complete effective environment settings.
  Other environments remain externally owned. The two production environments
  are explicitly managed; null inventory fields do not override their HCL.
- Legacy branch protection, hooks, Actions policy/default token permissions,
  additional Actions variables, Pages, vulnerability alerts and automated security
  fixes are unavailable through the permitted read coverage. The recorded
  401/403/404 responses mean **unknown**, not absence.
- Secrets cannot be recovered from inventory and are externally owned. No secret
  resource/value read, workflow change, deploy key, repository-wide default, or
  AWS resource is introduced.

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
