terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    spacelift = {
      source  = "spacelift-io/spacelift"
      version = "~> 1.55.0"
    }
  }
}

data "spacelift_account" "current" {}
data "spacelift_role" "space_admin" {
  slug = "space-admin"
}

locals {
  tofu_version = "1.12.6"
}

resource "spacelift_space" "oconnordev" {
  name = "oconnordev"

  # Every account has a root space that serves as the root for the space tree.
  # Except for the root space, all the other spaces must define their parents.
  parent_space_id = "root"

  # An optional description of a space.
  description = "oconnordev infrastructure"
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

resource "spacelift_stack" "oconnordev_general" {
  name        = "oconnordev-general"
  description = "general account"

  space_id = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/aws/general"

  autodeploy = false
  labels     = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}

resource "spacelift_stack" "oconnordev_production" {
  name        = "oconnordev-production"
  description = "production account"

  space_id = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/aws/production"

  autodeploy = false
  labels     = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}

resource "spacelift_stack" "oconnordev_hermes" {
  name        = "oconnordev-hermes"
  description = "Hermes account"

  space_id = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/aws/hermes"

  autodeploy = false
  labels     = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}

resource "spacelift_stack" "drumrollworld" {
  name        = "drumrollworld"
  description = "drumrollworld"

  space_id = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/aws/drumrollworld"

  autodeploy = false
  labels     = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
}

# The public MCP endpoint lives beside the domain and ACM certificate in the
# production account, while its AgentCore origin is owned by the Hermes stack.
resource "spacelift_stack_dependency" "production_hermes_gateway" {
  stack_id            = spacelift_stack.oconnordev_production.id
  depends_on_stack_id = spacelift_stack.oconnordev_hermes.id
}

resource "spacelift_stack_dependency_reference" "production_hermes_gateway_origin" {
  stack_dependency_id = spacelift_stack_dependency.production_hermes_gateway.id
  output_name         = "hermes_gateway_origin_hostname"
  input_name          = "TF_VAR_hermes_gateway_origin_hostname"
}

# The AWS IAM role is managed in the general account stack. Keep the Spacelift
# integration here and pass its non-secret identifiers to the general stack.
resource "spacelift_aws_integration" "oconnordev" {
  name = "oconnordev"

  role_arn                       = "arn:aws:iam::905418422177:role/spacelift"
  generate_credentials_in_worker = false
  space_id                       = spacelift_space.oconnordev.id
}

resource "spacelift_environment_variable" "general_spacelift_integration_id" {
  stack_id    = spacelift_stack.oconnordev_general.id
  name        = "TF_VAR_spacelift_integration_id"
  value       = spacelift_aws_integration.oconnordev.id
  write_only  = false
  description = "Spacelift AWS integration ID used by the management-account IAM role trust policy"
}

resource "spacelift_environment_variable" "general_spacelift_account_id" {
  stack_id    = spacelift_stack.oconnordev_general.id
  name        = "TF_VAR_spacelift_account_id"
  value       = data.spacelift_account.current.aws_account_id
  write_only  = false
  description = "Spacelift AWS account ID used by the management-account IAM role trust policy"
}

# Keep the Spacelift-provider attachments here; they bind the integration to stacks.
resource "spacelift_aws_integration_attachment" "oconnordev_general" {
  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = spacelift_stack.oconnordev_general.id
  read           = true
  write          = true
}

resource "spacelift_aws_integration_attachment" "oconnordev_production" {
  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = spacelift_stack.oconnordev_production.id
  read           = true
  write          = true
}

resource "spacelift_aws_integration_attachment" "oconnordev_hermes" {
  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = spacelift_stack.oconnordev_hermes.id
  read           = true
  write          = true
}

resource "spacelift_aws_integration_attachment" "drumrollworld" {
  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = spacelift_stack.drumrollworld.id
  read           = true
  write          = true
}
