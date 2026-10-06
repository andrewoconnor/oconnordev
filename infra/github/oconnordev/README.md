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
3. Set the administrative stack variable `TF_VAR_enable_github_repository_config=true` and apply again. This creates the GitHub configuration stack, attaches the auth context, and wires its inputs to outputs from both PRODUCTION and TOOLS. If its first run starts before dependency references are visible, rerun it after the administrative apply completes.

## Managed Actions variables and dependencies

The child stack manages exactly these three repository Actions variables:

- `OCONNORDEV_SITE_DEPLOY_ROLE_ARN` — from the PRODUCTION stack.
- `OCONNORDEV_CLOUDFRONT_DISTRIBUTION_ID` — from the PRODUCTION stack.
- `OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` — from the TOOLS stack's `tools_github_actions_broker_role_arn` output.

Accordingly, `oconnordev-github-repository-config` depends on both PRODUCTION and TOOLS. The broker ARN has no OpenTofu default or validation literal; Spacelift supplies it only through the TOOLS dependency reference.

The child stack does not manage other repository settings, Actions secrets, workflows, or AWS resources. If any of these Actions variables already exists, import it before first apply rather than attempting a duplicate create.
