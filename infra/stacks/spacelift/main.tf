terraform {
  required_providers {
    spacelift = {
      source = "spacelift-io/spacelift"
    }
  }
}

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
  project_root = "infra/stacks/spacelift"

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

import {
  to = spacelift_role_attachment.oconnordev_space_admin
  id = "STACK/01KT1DP4RKQSG56846W5SC9EE6"
}

resource "spacelift_stack" "oconnordev_general" {
  name        = "oconnordev-general"
  description = "general account"

  space_id = spacelift_space.oconnordev.id

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/stacks/general"

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
  project_root = "infra/stacks/production"

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
  project_root = "infra/stacks/drumrollworld"

  autodeploy = false
  labels     = ["managed", "depends-on:${spacelift_stack.oconnordev.id}"]

  terraform_workflow_tool      = "OPEN_TOFU"
  terraform_version            = local.tofu_version
  terraform_smart_sanitization = true
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

# These AWS resources are imported into infra/stacks/general/spacelift-iam.tf.
# Detach them from this stack's state without destroying the live IAM role or policy.
removed {
  from = aws_iam_role.spacelift

  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_iam_role_policy_attachment.spacelift

  lifecycle {
    destroy = false
  }
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

resource "spacelift_aws_integration_attachment" "drumrollworld" {
  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = spacelift_stack.drumrollworld.id
  read           = true
  write          = true
}
