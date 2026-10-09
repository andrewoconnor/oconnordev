# Dedicated GitHub App authentication bootstrap

Create a separate GitHub App for OpenTofu repository-settings management (suggested name: `oconnordev-repo-settings`). Do not use, broaden, or reuse the Hermes GitHub App or Spacelift's managed VCS integration credentials.

Configure the App with only:

- Repository permission `Variables`: read and write
- `Metadata`: read-only

Install it only on `andrewoconnor/oconnordev`, selecting only that repository. It must not be installed on any other repository. The App creation/installation is a GitHub UI bootstrap; OpenTofu manages only the repository Actions variables and the Spacelift stack/context wiring.

After creating and installing the dedicated App, add these values to the dedicated Spacelift context `oconnordev-github-provider-auth`:

- `TF_VAR_github_app_id` — App ID (plain value)
- `TF_VAR_github_app_installation_id` — installation ID for `andrewoconnor/oconnordev` (plain value)
- `TF_VAR_github_app_private_key` — private key contents (secret/write-only)

The private key is an ephemeral provider input and is not written to OpenTofu plan/state or outputs. It is stored once in the dedicated Spacelift context for centralized rotation. The context is attached only to `oconnordev-github-repository-config`.

## Provisioning order

1. Apply the administrative `infra/spacelift` stack with `enable_github_repository_config = false`. This creates the dedicated, empty auth context without creating the child stack.
2. Create the dedicated GitHub App with the permissions and single-repository installation above, then populate its App ID, installation ID, and private key in the context as described. Do not put the key in OpenTofu, a repo variable, or chat.
3. Set the administrative stack variable `TF_VAR_enable_github_repository_config=true` and apply again. This creates the GitHub configuration stack, attaches the auth context, and wires its inputs to outputs from PRODUCTION, TOOLS, and DRUMROLLWORLD. If its first run starts before dependency references are visible, rerun it after the administrative apply completes.

## Managed Actions variables and dependencies

The child stack has five managed repository Actions variables (the two
DrumrollWorld resources are gated until both deployment inputs are populated):

- `OCONNORDEV_SITE_DEPLOY_ROLE_ARN` — from the PRODUCTION stack.
- `OCONNORDEV_CLOUDFRONT_DISTRIBUTION_ID` — from the PRODUCTION stack.
- `OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` — from the TOOLS stack's `tools_github_actions_broker_role_arn` output.

- `DRUMROLLWORLD_SITE_DEPLOY_ROLE_ARN` — from the DRUMROLLWORLD stack.
- `DRUMROLLWORLD_CLOUDFRONT_DISTRIBUTION_ID` — from the DRUMROLLWORLD stack.

Accordingly, `oconnordev-github-repository-config` has three producer dependencies:
PRODUCTION, TOOLS, and DRUMROLLWORLD. The broker ARN has no OpenTofu default or
validation literal; Spacelift supplies it only through the TOOLS dependency
reference. The two DrumrollWorld variables are created only when both producer
inputs are non-empty.

The five variables are already managed in the existing Spacelift state; do not
reimport them. This documentation update does not adopt or import any additional
repository settings. The child stack does not manage general repository settings,
merge flags, rulesets, collaborators, labels, environments, hooks, Pages, Actions
policy, Actions secrets, workflows, or AWS resources. Do not add settings HCL
without a verified inventory, exact provider resource/import contract, and a
separate reviewed adoption plan.

The [native MCP settings-read prerequisite](../../../docs/runbooks/github-settings-read.md)
provides deliberately incomplete read coverage after user merge/apply. Its
machine-user PAT is separate from this dedicated Variables-only provider App;
do not reuse or broaden this App for MCP inventory.
