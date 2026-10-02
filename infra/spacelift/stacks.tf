resource "spacelift_stack" "accounts" {
  for_each = local.account_stacks

  name        = each.value.name
  description = each.value.description
  space_id    = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = each.value.project_root

  autodeploy = false
  labels     = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}
