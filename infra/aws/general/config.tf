data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  config_bucket_name = "oconnordev-config"

  config_recorded_resource_types = [
    "AWS::CloudTrail::Trail",
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::KMS::Key",
    "AWS::S3::Bucket",
    "AWS::SecretsManager::Secret",
  ]
}

variable "enable_management_account_audit" {
  description = "Create the organization trail (cloudtrail.tf) and this account's Config recorder and delivery channel. Enable only after the security stack has created the destination buckets and the existing trail has been imported into this stack's state."
  type        = bool
  default     = true
}

data "aws_iam_policy_document" "config_recorder_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "config_recorder" {
  count = var.enable_management_account_audit ? 1 : 0

  name               = "oconnordev-config-recorder"
  assume_role_policy = data.aws_iam_policy_document.config_recorder_assume_role.json
}

resource "aws_iam_role_policy_attachment" "config_recorder" {
  count = var.enable_management_account_audit ? 1 : 0

  role       = aws_iam_role.config_recorder[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_config_configuration_recorder" "management" {
  # checkov:skip=CKV2_AWS_48:Deliberate. This check wants the recorder to record every possible resource type, which is exactly the configuration this design exists to avoid -- AWS Config is billed per configuration item recorded. The recording group lists the resource types this organization actually deploys.
  count = var.enable_management_account_audit ? 1 : 0

  name     = "default"
  role_arn = aws_iam_role.config_recorder[0].arn

  recording_group {
    all_supported = false

    include_global_resource_types = false
    resource_types                = local.config_recorded_resource_types
  }
}

resource "aws_config_delivery_channel" "management" {
  count = var.enable_management_account_audit ? 1 : 0

  name           = "default"
  s3_bucket_name = local.config_bucket_name

  depends_on = [aws_config_configuration_recorder.management]
}

resource "aws_config_configuration_recorder_status" "management" {
  # checkov:skip=CKV2_AWS_45:Deliberate. Recording every supported resource type is the configuration that makes this account expensive -- AWS Config is billed per configuration item recorded. The recording group in this stack lists the resource types this organization actually deploys; recording all supported types is the opposite of the intent of this change.
  count = var.enable_management_account_audit ? 1 : 0

  name       = aws_config_configuration_recorder.management[0].name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.management]
}
