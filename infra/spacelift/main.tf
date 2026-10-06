data "spacelift_account" "current" {}
data "spacelift_role" "space_admin" {
  slug = "space-admin"
}

locals {
  tofu_version = "1.12.6"

  managed_stacks = {
    general = {
      name                     = "oconnordev-general"
      description              = "general account"
      project_root             = "infra/aws/general"
      additional_project_globs = ["infra/aws/accounts.json", "infra/aws/cost-export-schema.json"]
    }
    production = {
      name                     = "oconnordev-production"
      description              = "production account"
      project_root             = "infra/aws/production"
      additional_project_globs = ["infra/aws/accounts.json"]
    }
    tools = {
      name        = "oconnordev-tools"
      description = "OCONNORDEV-TOOLS AWS account"
      project_root = "infra/aws/tools"
      additional_project_globs = [
        "infra/aws/accounts.json",
        "agents/hermes/rotation/*.py",
        "agents/hermes/adapter/*-mcp-tools.json",
      ]
    }
    security = {
      name                     = "oconnordev-security"
      description              = "security account"
      project_root             = "infra/aws/security"
      additional_project_globs = ["infra/aws/accounts.json", "infra/aws/cost-export-schema.json"]
    }
    drumrollworld = {
      name                     = "drumrollworld"
      description              = "DrumrollWorld static-site workload in the PRODUCTION account"
      project_root             = "infra/aws/drumrollworld"
      additional_project_globs = ["infra/aws/accounts.json"]
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

  repository               = "oconnordev"
  branch                   = "master"
  project_root             = "infra/spacelift"
  additional_project_globs = ["infra/aws/accounts.json"]

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
