data "spacelift_account" "current" {}
data "spacelift_role" "space_admin" {
  slug = "space-admin"
}

locals {
  tofu_version = "1.12.6"

  account_stacks = {
    general = {
      name         = "oconnordev-general"
      description  = "general account"
      project_root = "infra/aws/general"
    }
    production = {
      name         = "oconnordev-production"
      description  = "production account"
      project_root = "infra/aws/production"
    }
    tools = {
      name        = "oconnordev-tools"
      description = "OCONNORDEV-TOOLS AWS account"
      # Keep the existing stack ID/state while moving its project root.
      project_root = "infra/aws/tools"
    }
    security = {
      name         = "oconnordev-security"
      description  = "security account"
      project_root = "infra/aws/security"
    }
    drumrollworld = {
      name         = "drumrollworld"
      description  = "drumrollworld"
      project_root = "infra/aws/drumrollworld"
    }
  }
}

resource "spacelift_space" "oconnordev" {
  name            = "oconnordev"
  parent_space_id = "root"
  description     = "oconnordev infrastructure"
}

resource "spacelift_stack" "oconnordev" {
  name        = "oconnordev"
  description = "administrative stack"

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/spacelift"

  autodeploy            = false
  github_action_deploy  = false
  protect_from_deletion = true

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}

resource "spacelift_role_attachment" "oconnordev_space_admin" {
  stack_id = spacelift_stack.oconnordev.id
  role_id  = data.spacelift_role.space_admin.id
  space_id = "root"
}
