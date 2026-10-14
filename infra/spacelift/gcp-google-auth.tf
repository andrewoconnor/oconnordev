# Standalone GCP discovery stack: never join the AWS managed_stacks loop.
resource "spacelift_stack" "gcp_google_auth" {
  name        = "oconnordev-gcp-google-auth"
  description = "Read-only discovery of the existing Google Auth project; import requires a later owner-approved PR"
  space_id    = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/gcp/google-auth"

  autodeploy            = false
  protect_from_deletion = true
  labels                = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}

resource "spacelift_gcp_service_account" "google_auth" {
  stack_id = spacelift_stack.gcp_google_auth.id
  # A token scope is not an IAM permission. Google IAM enforces read-only access.
  token_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
}

output "gcp_google_auth_service_account_email" {
  description = "Native Spacelift service account email; owner grants project roles/browser after administrative apply."
  value       = spacelift_gcp_service_account.google_auth.service_account_email
}
