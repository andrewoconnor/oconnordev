variable "spacelift_run_id" {
  type = string
}

terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.66.0"
    }
  }
}

provider "aws" {
  assume_role {
    role_arn     = "arn:aws:iam::421680664125:role/spacelift"
    session_name = var.spacelift_run_id
    external_id  = "spacelift-general"
  }

  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

locals {
  # The Hermes adapter is application code rather than Terraform, so it lives
  # under agents/ at the repository root instead of inside this stack.
  # `path.root` is this stack's directory (infra/aws/hermes), so three levels
  # up is the repository root.
  repo_root    = "${path.root}/../../.."
  adapter_root = "${local.repo_root}/agents/hermes/adapter"
}

output "aws_account_id" {
  description = "AWS account ID reached by the Hermes stack's Spacelift role."
  value       = data.aws_caller_identity.current.account_id
}
