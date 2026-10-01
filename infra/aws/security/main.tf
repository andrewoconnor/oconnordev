variable "spacelift_run_id" {
  type = string
}

variable "security_account_id" {
  description = "AWS account ID of the security (Security Tooling) account. Supplied as TF_VAR_security_account_id on the oconnordev-security stack because the account is created out of band and no other stack knows its ID."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.security_account_id))
    error_message = "security_account_id must be a 12-digit AWS account ID."
  }
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
    role_arn     = "arn:aws:iam::${var.security_account_id}:role/spacelift"
    session_name = var.spacelift_run_id
    external_id  = "spacelift-general"
  }

  region = "us-east-1"
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  # The security account is the organization's read-only vantage point. AWS's
  # multi-account guidance places a Security Tooling (Audit) account in the
  # Security OU and delegates the aggregation services to it, for two reasons
  # that both apply here: the management account should hold no resources, and
  # service control policies do not restrict users or roles in the management
  # account -- but they do apply to a member account that is a delegated
  # administrator. A read vantage point in a member account is therefore inside
  # the organization's own guardrails; one in the management account is not.
  config_delivery_bucket_name = "oconnordev-config-${var.security_account_id}"

  # Deliberately narrow. AWS Config is billed per configuration item recorded,
  # so "all supported resource types" in every account is what turns a
  # sub-dollar line item into a monthly bill. This is the set this organization
  # actually deploys and would want to read back.
  config_recorded_resource_types = [
    "AWS::CloudFront::Distribution",
    "AWS::Cognito::UserPool",
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::KMS::Key",
    "AWS::Lambda::Function",
    "AWS::Route53::HostedZone",
    "AWS::S3::Bucket",
    "AWS::SecretsManager::Secret",
  ]
}

output "aws_account_id" {
  description = "AWS account ID reached by the security stack's Spacelift role."
  value       = data.aws_caller_identity.current.account_id
}
