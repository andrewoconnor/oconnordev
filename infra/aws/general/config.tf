# ---------------------------------------------------------------------------
# AWS Config in the management account.
#
# This account had no recorder before this change. The organization aggregator
# in the security account reported three source accounts, not four, so the
# management account's own configuration -- including the Organizations, IAM
# Identity Center and delegated-administrator resources that exist only here --
# was outside the organization-wide view. Adding the recorder here is what
# closes that gap.
#
# Delivery goes to the central Config bucket in the security account, the same
# bucket PRODUCTION, HERMES and SECURITY write to. That bucket is declared in
# infra/aws/security/audit-bucket-config.tf.
#
# ---------------------------------------------------------------------------
# APPLY ORDER -- READ BEFORE APPLYING
# ---------------------------------------------------------------------------
#
# The delivery channel cannot be created before the bucket exists. AWS Config's
# PutDeliveryChannel returns NoSuchBucketException, "The specified Amazon S3
# bucket does not exist":
#
#   https://docs.aws.amazon.com/config/latest/APIReference/API_PutDeliveryChannel.html
#
# The bucket is created by the security stack, and the security stack depends on
# this one. That direction is fixed and cannot be reversed: the delegated
# administrator registrations this stack owns must exist before the security
# stack can use them, so a reverse dependency would be a cycle.
#
# The consequence is that on the first apply this stack runs before the bucket
# exists. Left ungated, the delivery channel would fail and, because the
# security stack waits on this one, that failure would block the whole chain.
#
# The recorder and its delivery channel are therefore gated behind
# var.enable_management_account_config, which defaults to false. Turning
# management-account recording on is a deliberate two-step:
#
#   1. Apply this change. The security stack then creates the two buckets.
#   2. Set enable_management_account_config = true and apply this stack again.
#
# Step 2 is a one-line change. It is separate only because the bucket it writes
# to cannot exist before this stack has run.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  # The central Config bucket lives in the security account, declared in
  # infra/aws/security/audit-bucket-config.tf. It is a literal rather than a
  # Spacelift output reference because this stack is upstream of the security
  # stack, so referencing its output would create the reverse dependency
  # described above. Keep in sync with the security stack if it is ever renamed.
  config_bucket_name = "oconnordev-config"

  # Must match the delivery path the Config bucket policy grants:
  # <prefix>/AWSLogs/<accountId>/Config/* in
  # infra/aws/security/audit-bucket-config.tf.
  config_key_prefix = "config"

  config_recorded_resource_types = [
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::KMS::Key",
    "AWS::S3::Bucket",
    "AWS::SecretsManager::Secret",
  ]
}

variable "enable_management_account_config" {
  description = "Record the management account's own configuration and deliver it to the central Config bucket. Requires the security stack to have created that bucket first; see the apply-order note at the top of this file."
  type        = bool
  default     = false
}

data "aws_iam_policy_document" "config_recorder_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    # Confused-deputy protection: only AWS Config acting for this account may
    # assume the recorder role.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "config_recorder" {
  count = var.enable_management_account_config ? 1 : 0

  name               = "oconnordev-config-recorder"
  assume_role_policy = data.aws_iam_policy_document.config_recorder_assume_role.json
}

# service-role/AWS_ConfigRole is also what satisfies the cross-account
# HeadBucket requirement in the Config bucket's policy: it grants s3:ListBucket
# on every resource, which is the permission AWS Config calls the S3 HeadBucket
# API with to determine the bucket location. No inline policy is needed for it,
# and none is needed for delivery either -- the PutObject writes into the bucket
# are made by the Config service principal, not by this role.
resource "aws_iam_role_policy_attachment" "config_recorder" {
  count = var.enable_management_account_config ? 1 : 0

  role       = aws_iam_role.config_recorder[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_config_configuration_recorder" "management" {
  # checkov:skip=CKV2_AWS_48:Deliberate. This check wants the recorder to record every possible resource type, which is exactly the configuration this design exists to avoid -- AWS Config is billed per configuration item recorded. The recording group lists the resource types this organization actually deploys.
  count = var.enable_management_account_config ? 1 : 0

  name     = "default"
  role_arn = aws_iam_role.config_recorder[0].arn

  recording_group {
    all_supported = false

    # include_global_resource_types must stay false. AWS rejects the recorder
    # with InvalidRecordingGroupException when it is true while all_supported is
    # false ("Before you set this field to true, set the allSupported field of
    # RecordingGroup to true"), and it is unnecessary here: with all_supported
    # false and the global IAM resource types listed in resource_types, Config
    # records them regardless of this flag.
    include_global_resource_types = false
    resource_types                = local.config_recorded_resource_types
  }
}

resource "aws_config_delivery_channel" "management" {
  count = var.enable_management_account_config ? 1 : 0

  name           = "default"
  s3_bucket_name = local.config_bucket_name
  s3_key_prefix  = local.config_key_prefix

  depends_on = [aws_config_configuration_recorder.management]
}

resource "aws_config_configuration_recorder_status" "management" {
  # checkov:skip=CKV2_AWS_45:Deliberate. Recording every supported resource type is the configuration that makes this account expensive -- AWS Config is billed per configuration item recorded. The recording group in this stack lists the resource types this organization actually deploys; recording all supported types is the opposite of the intent of this change.
  count = var.enable_management_account_config ? 1 : 0

  name       = aws_config_configuration_recorder.management[0].name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.management]
}

output "config_recording_enabled" {
  description = "Whether the management account's Config recorder is configured and delivering to the central Config bucket."
  value       = var.enable_management_account_config
}
