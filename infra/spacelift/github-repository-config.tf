resource "spacelift_context" "github_provider_auth" {
  name        = "oconnordev-github-provider-auth"
  description = "GitHub App authentication for the oconnordev repository configuration stack. Populate TF_VAR_github_app_id and TF_VAR_github_app_installation_id as plain context variables and TF_VAR_github_app_private_key as a secret/write-only context variable; do not put the private key in Terraform."
  space_id    = spacelift_space.oconnordev.id
  labels      = ["managed"]
}

resource "spacelift_context_attachment" "github_provider_auth" {
  count = var.enable_github_repository_config ? 1 : 0

  context_id = spacelift_context.github_provider_auth.id
  stack_id   = spacelift_stack.github_repository_config[0].id
  priority   = 0
}
