# GitHub repository configuration

Root `infra/github/oconnordev` runs as `oconnordev-github-repository-config`.
Use a dedicated GitHub App installed only on `andrewoconnor/oconnordev`; never
reuse Hermes/MCP PAT/App or Spacelift VCS credentials. Required repository
permissions are Metadata read, Variables read/write, Administration read/write,
Issues read/write, and Environments read/write. The owner alone approves App
creation, installation and permission updates. Do not add Contents, Secrets or
Workflows permissions for this root.

## Authentication bootstrap

1. Apply administrative `infra/spacelift` with
   `enable_github_repository_config=false` to create the dedicated empty context.
2. Owner creates/installs the dedicated App and populates
   `oconnordev-github-provider-auth`: `TF_VAR_github_app_id`,
   `TF_VAR_github_app_installation_id`, and secret/write-only
   `TF_VAR_github_app_private_key`. The key is an ephemeral provider input;
   never put it in code, plan/state, output or chat. Attach this context only to
   the repository-configuration stack.
3. Owner enables `TF_VAR_enable_github_repository_config=true`, reviews/applies
   the administrative stack and waits for producer dependency inputs. Reconcile
   existing resources at their exact state addresses rather than creating duplicates.

## Managed inputs and settings

Six repository Actions variables come from three producer stacks:

| Producer | Variables |
| --- | --- |
| `oconnordev-resume` | `OCONNORDEV_SITE_DEPLOY_ROLE_ARN`, `OCONNORDEV_CLOUDFRONT_DISTRIBUTION_ID` |
| TOOLS | `OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN`, `DRUMROLLWORLD_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` |
| DrumrollWorld | `DRUMROLLWORLD_SITE_DEPLOY_ROLE_ARN`, `DRUMROLLWORLD_CLOUDFRONT_DISTRIBUTION_ID` |

Dependency references, not literal/default broker ARNs, supply these values.
DrumrollWorld site variables are gated until both site inputs are populated.
The root additionally declares one master ruleset, eight singular labels,
default branch and topics with preservation protections. See
[settings operations](../../../docs/runbooks/github-settings-adoption.md)
for exact identities, provider limitations and fresh owner plan gates.

## Production environments

`site-environments.tf` owns `oconnordev-production` and
`drumrollworld-production`, each with exactly branch master and no tag policy.
Follow [environment bootstrap](../../../docs/runbooks/infrastructure-bootstrap.md#tested-artifact-environment-bootstrap):
protect and test both environment gates before IAM environment trust, reconcile
objects into the existing stack, then read back protection before enabling
workflows. Offline mocks are not live enforcement proof.

Unsupported settings remain externally owned: no broad `github_repository`,
collaborator set, merge defaults, hooks, Pages, Actions policy/secrets or workflow
resources. Inherent owner access is not an importable collaborator grant.
The [native settings reads](../../../docs/runbooks/github-settings-read.md)
are partial; unknown/null fields are not guessed defaults. Preserve import blocks,
provider locks and state addresses; only the owner approves live plans/applies.
