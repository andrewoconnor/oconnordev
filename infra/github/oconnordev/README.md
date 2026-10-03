# GitHub App authentication bootstrap

The administrative Spacelift root creates this stack's dedicated context, but deliberately does not store App credentials in Terraform. Before enabling the child stack, add these environment variables to the context in Spacelift:

- `TF_VAR_github_app_id` — existing GitHub App ID (plain value)
- `TF_VAR_github_app_installation_id` — installation ID for `andrewoconnor/oconnordev` (plain value)
- `TF_VAR_github_app_private_key` — existing App private key contents (mark secret/write-only)

The private key variable is `ephemeral` in the child Terraform root, so it is not written to the plan or state. It is held once in the dedicated context for central rotation. The App must be installed on `andrewoconnor/oconnordev` with repository Variables read/write permission. This context is attached only to `oconnordev-github-repository-config`. Do not use or copy the managed Spacelift VCS integration credentials; do not configure a PAT.

## Provisioning order

1. Apply the administrative `infra/spacelift` stack with `enable_github_repository_config = false`. This creates the empty, dedicated auth context without creating a child stack or placing any credential in Terraform state.
2. Populate the three variables above in that context using Spacelift's UI. The App private key exists only as a Spacelift secret and can be rotated there without duplicating it into Terraform stack variables/state.
3. Set the administrative stack variable `TF_VAR_enable_github_repository_config=true` and apply again. This creates the GitHub configuration stack, attaches the auth context, and wires its inputs to the PRODUCTION outputs. If its first run starts before dependency references are visible, rerun it after the administrative apply completes.

The child stack manages only the two named repository Actions variables. It does not manage repository settings, Actions secrets, workflows, or AWS resources.
