resource "spacelift_stack" "accounts" {
  for_each = local.managed_stacks

  name        = each.value.name
  description = each.value.description
  space_id    = spacelift_space.oconnordev.id

  repository               = "oconnordev"
  branch                   = "master"
  project_root             = each.value.project_root
  additional_project_globs = each.value.additional_project_globs

  autodeploy            = false
  protect_from_deletion = true
  labels                = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}

resource "spacelift_stack" "github_repository_config" {
  count = var.enable_github_repository_config ? 1 : 0

  name        = "oconnordev-github-repository-config"
  description = "Manage Actions variables for the oconnordev repository"
  space_id    = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/github/oconnordev"

  autodeploy            = false
  protect_from_deletion = true
  labels                = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}
