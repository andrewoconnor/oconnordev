# Dedicated GitHub App authentication bootstrap

Create a separate GitHub App for Terraform repository-settings management (suggested name: `oconnordev-repo-settings`). Do not use, broaden, or reuse the Hermes GitHub App or Spacelift's managed VCS integration credentials.

Configure the App with only:

- Repository permission `Variables`: read and write
- `Metadata`: read-only

Install it only on `andrewoconnor/oconnordev`, selecting only that repository. It must not be installed on any other repository. The App creation/installation is a GitHub UI bootstrap; Terraform manages only the repository Actions variables and the Spacelift stack/context wiring.

After creating and installing the dedicated App, add these values to the dedicated Spacelift context `oconnordev-github-provider-auth`:

- `TF_VAR_github_app_id` — App ID (plain value)
- `TF_VAR_github_app_installation_id` — installation ID for `andrewoconnor/oconnordev` (plain value)
- `TF_VAR_github_app_private_key` — private key contents (secret/write-only)

The private key is an ephemeral provider input and is not written to Terraform plan/state or outputs. It is stored once in the dedicated Spacelift context for centralized rotation. The context is attached only to `oconnordev-github-repository-config`.

## Provisioning order

1. Apply the administrative `infra/spacelift` stack with `enable_github_repository_config = false`. This creates the dedicated, empty auth context without creating the child stack.
2. Create the dedicated GitHub App with the permissions and single-repository installation above, then populate its App ID, installation ID, and private key in the context as described. Do not put the key in Terraform, a repo variable, or chat.
3. Set the administrative stack variable `TF_VAR_enable_github_repository_config=true` and apply again. This creates the GitHub configuration stack, attaches the auth context, and wires its inputs to the PRODUCTION outputs. If its first run starts before dependency references are visible, rerun it after the administrative apply completes.

The child stack manages only the two named repository Actions variables. It does not manage repository settings, Actions secrets, workflows, or AWS resources. If either Actions variable already exists, import it before first apply rather than attempting a duplicate create.
