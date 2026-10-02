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
    role_arn     = "arn:aws:iam::482921124454:role/spacelift"
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
  # The two central audit buckets this account owns: organization CloudTrail
  # logs in one, Config history from all four accounts in the other. Both are
  # declared in audit-bucket-cloudtrail.tf and audit-bucket-config.tf. The names
  # are literals rather than derived from this account's ID because three other
  # stacks point their Config delivery channels at the Config bucket; the
  # general stack in particular is upstream of this one, so a Spacelift output
  # reference would create the reverse dependency the stack graph forbids.
  cloudtrail_bucket_name = "oconnordev-cloudtrail"
  config_bucket_name     = "oconnordev-config"

  # Key prefixes inside those buckets. CloudTrail and Config both write under an
  # AWSLogs/<account-id>/ layout, so each gets its own prefix and the bucket
  # policies can name exact paths rather than sharing one namespace.
  cloudtrail_key_prefix = "cloudtrail"
  config_key_prefix     = "config"

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
