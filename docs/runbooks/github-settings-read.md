# Native GitHub settings-read prerequisite

## Scope and status

This change adds four existing native tools to the existing hosted GitHub MCP
manifest and AWS Cedar read allowlist. It is a **partial inventory prerequisite**,
not complete repository adoption: no repository settings were imported, no new
settings HCL was created, and no live inventory, current token permissions, or
GitHub App permissions were verified by this change. The five existing managed
Actions variables must not be reimported; see the [provider root](../../infra/github/oconnordev/README.md).
The next inventory/adoption stage starts only after user merge and apply.

The source contract is pinned to
[`github/github-mcp-server@85598ba6e1256f7ebf4867b95d63b833c4549264`](https://github.com/github/github-mcp-server/tree/85598ba6e1256f7ebf4867b95d63b833c4549264).
The hosted endpoint itself is not an immutable checkout: read back its actual
schemas and behavior after rollout rather than assuming the public source pin
proves today's hosted implementation.

| Tool | Obtainable coverage and limits |
| --- | --- |
| `repository_ruleset_read` | Only `level="repository"`, `method="list"` or `"get"`, and explicit boolean `includes_parents=false`. List summaries, then get each returned repository ruleset ID for conditions/rules. No inherited organization/enterprise rulesets, effective branch rules, or rule suites. |
| `list_repository_collaborators` | Paginated repository collaborators and their reported access. Request `affiliation="all"` for that view; this is not an inventory of invitations, teams, organization membership, or every indirect grant. |
| `list_label` | Label names, IDs, colors, descriptions and `totalCount`. Upstream fetches **at most 100**, ordered by issue count, and exposes no page/cursor argument. |
| `get_label` | Details for a known exact label `name`; cannot discover labels omitted by the list cap. |

All four require `owner="andrewoconnor"` and a `repo` present in
`hermes_github_allowed_repositories`; missing owner/repo denies access. The
ruleset method/level/parent restrictions are enforced by Cedar, not just advice.
An empty allowlist creates no permits. Existing `hermes/*` branch writes and
draft-only PR constraints remain unchanged. No ruleset/settings write tool is
exposed. No new server, Lambda, secret, or fixed-cost resource is introduced;
the existing gateway authorizer, OAuth scope and EXTERNAL credential role chain
are unchanged.

These tools do **not** read repository merge flags/general settings, Actions
policy/settings/variables/secrets, environments, webhooks, Pages, classic branch
protection, or complete organization/enterprise policy. Missing coverage stays
unknown; do not invent defaults or convert omissions into destructive HCL.

## Collection contract

1. Discover all gateway `tools/list` pages (`nextCursor`) and compare the exact
   client tool set with the manifests. Catalog pagination is separate from
   repository-data pagination.
2. For collaborators, use `page`/`perPage` (maximum 100) and the desired
   `affiliation`; advance pages until exhausted. For repository rulesets use
   `method="list"`, `page`/`perPage`, and `includes_parents=false` on **every**
   page. Follow available pagination metadata or continue through an empty page
   when a full final page is ambiguous. Deduplicate IDs, persist each batch, and
   record coverage and failures. Do not assume one page is complete.
3. Get each discovered ruleset with its `ruleset_id`, the same owner/repo,
   `level="repository"`, `method="get"`, and `includes_parents=false`.
4. Compare the unique returned label count with `totalCount`. If they differ,
   the result is incomplete, even when 100 labels were returned. Do not fabricate
   a cursor or assume `get_label` can discover unknown names. Record the cap as
   a coverage gap; any separate read path requires a later reviewed change.
5. Keep missing/forbidden/unavailable fields distinct from actual empty arrays.
   In particular GitHub's ruleset `bypass_actors` is only returned with repository
   write access. **An omitted `bypass_actors` is unknown, never empty.** Do not
   adopt a ruleset with an invented empty bypass list.

## Permission review and secure token bootstrap

No present token/App permissions are asserted here. First probe the approved
read calls with the existing credential, read back the result, and distinguish
Cedar denial, missing hosted catalog support, authentication failure, upstream
403/404, and successful partial data. A listing alone proves neither successful
calls nor complete fields. Do not broaden permissions to fix a bad payload,
missing pagination, stale catalog, or missing bypass data without this readback.

Candidate fine-grained GitHub requirements to review against the actual endpoint:

- Repository ruleset list/get: Metadata read; public resources may be readable
  without authentication. Hidden bypass actors have a separate upstream caveat.
- Collaborator list: Metadata read **and the authenticated identity must have
  write, maintain, or admin repository access**. A token permission alone does
  not confer that identity role.
- Labels: Issues read or Pull requests read, plus normal Metadata read.

GitHub's ruleset GET documentation says bypass actors are only returned with
write access. A complete bypass inventory may require repository Administration
**write** in the fine-grained credential as well as sufficient identity access.
This is a user-approved credential-permission exception to **read hidden data**,
not authorization to expose write-capable MCP tools. Never grant it automatically.
If the user accepts incomplete inventory, preserve bypass actors as unknown.
See [GitHub's ruleset GET contract](https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset),
[collaborator list contract](https://docs.github.com/en/rest/collaborators/collaborators#list-repository-collaborators),
and [labels contract](https://docs.github.com/en/rest/issues/labels#list-labels-for-a-repository).

Only after the existing-token readback and user-approved review should the user
rotate a repository-scoped machine-user token in GitHub's secure UI and replace
its value in the **existing** AWS Secrets Manager secure UI entry
`/hermes/github/machine-user-pat`. Preserve the JSON object/key expected by
`hermes_github_machine_user_pat_json_key` (default `api_key`), existing encryption,
metadata ownership and EXTERNAL provider source. Never put the token in chat,
logs, CLI output, Terraform inputs/outputs/state, or a secret-version resource.
Do not read the secret value to verify rotation: retry the approved read call
through the existing AgentCore role chain and read back its non-secret result.
Do not reuse or broaden the dedicated OpenTofu provider App or Spacelift VCS
integration credentials for MCP.

## User-controlled rollout and rollback

1. Review and merge this prerequisite; inspect the TOOLS speculative plan.
   The existing manifest hash trigger **replaces the GitHub gateway target** to
   refresh its DEFAULT catalog. This is a target-specific replacement, with
   dependent GitHub Cedar policy updates and possible temporary GitHub MCP
   unavailability. It is not a gateway/authorizer replacement, but review the
   real plan for unrelated cascades before confirming.
2. User confirms/applies TOOLS **before** deploying/reloading the new adapter.
   During mixed revisions exact-manifest discovery can fail closed. Read back
   the full catalog and policy status; offline tests do not establish AgentCore
   semantic acceptance or live credential health.
3. User deploys/reloads the adapter using the existing deployment procedure.
   Run existing read-only smoke checks, then individually probe these four
   reads and repository/owner/ruleset deny cases. The existing general smoke
   command only probes its representative GitHub file read; it does not certify
   settings coverage or bypass completeness.
4. Record partial inventory, errors, pagination and missing fields without
   secrets. Review token changes only if those actual readbacks require them.
   Complete adoption/import is a separate approved stage after this merge/apply.

To roll back, revert the four manifest/read-permit additions together, review
and apply TOOLS (another catalog target replacement), then roll back/reload the
adapter. Revoke any separately approved excess token permissions in the secure
UI and re-probe remaining reads. No automatic deployment or credential change
is part of this prerequisite.

## Offline verification

`mise run test:python` installs the pinned test-only `cedarpy` wheel from
`scripts/ci/requirements-test.txt` (initial setup may need network), then renders
actual checked-in Terraform locals and the read-policy heredoc in an isolated
provider-free OpenTofu fixture and evaluates standard Cedar authorization.
The tests exercise all four exact action names, owner/repository isolation,
ruleset restrictions, default deny and secret/Lambda guardrails. No live AWS,
GitHub, backend, or secret reads occur. Adapter tests prove exact listing,
routing and manifest headers; mocked OpenTofu tests prove permit/catalog
wiring, empty allowlist denial and the unchanged EXTERNAL source:

```sh
mise run lint:python
mise run test:python
mise run test:opentofu-boundary
```
