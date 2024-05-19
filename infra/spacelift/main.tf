terraform {
  required_providers {
    spacelift = {
      source = "spacelift-io/spacelift"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

data "spacelift_current_stack" "this" {}

resource "spacelift_space" "oconnordev" {
  name = "oconnordev"

  # Every account has a root space that serves as the root for the space tree.
  # Except for the root space, all the other spaces must define their parents.
  parent_space_id = "root"

  # An optional description of a space.
  description = "oconnordev infrastructure"
}

resource "spacelift_stack" "oconnordev_general" {
  name        = "oconnordev-general"
  description = "general account"

  repository   = "oconnordev"
  branch       = "master"
  project_root = "infra/envs/general"

  autodeploy = true
  labels     = ["managed", "depends-on:${data.spacelift_current_stack.this.id}"]

  terraform_workflow_tool = "OPEN_TOFU"
}

# Needed for generating the correct role ARNs
data "aws_caller_identity" "current" {}

locals {
  role_name = "spacelift"
  role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.role_name}"
}

# Create the AWS integration before creating your IAM role. The integration needs to exist
# in order to generate the external ID used for role assumption.
resource "spacelift_aws_integration" "oconnordev" {
  name = "oconnordev"

  # We need to set the ARN manually rather than referencing the role to avoid a circular dependency
  role_arn                       = local.role_arn
  generate_credentials_in_worker = false
  space_id                       = spacelift_space.oconnordev.id
}

data "spacelift_aws_integration_attachment_external_id" "oconnordev" {
  integration_id = spacelift_aws_integration.oconnordev.id

  stack_id       = "*"
  read           = true
  write          = true
}

# Create the IAM role, using the `assume_role_policy_statement` from the data source.
resource "aws_iam_role" "spacelift" {
  name = local.role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      jsondecode(data.spacelift_aws_integration_attachment_external_id.oconnordev.assume_role_policy_statement),
    ]
  })
}

resource "aws_iam_role_policy_attachment" "spacelift" {
  role       = aws_iam_role.spacelift.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# Attach the integration to any stacks or modules that need to use it
resource "spacelift_aws_integration_attachment" "oconnordev_terraform_starter" {
  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = data.spacelift_current_stack.this.id
  read           = true
  write          = true

  # The role needs to exist before we attach since we test role assumption during attachment.
  depends_on = [
    aws_iam_role.spacelift
  ]
}

resource "spacelift_aws_integration_attachment" "oconnordev_general" {
  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = spacelift_stack.oconnordev_general.id
  read           = true
  write          = true

  # The role needs to exist before we attach since we test role assumption during attachment.
  depends_on = [
    aws_iam_role.spacelift
  ]
}
