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
# Both resources this stack contributes to the audit plane write into buckets
# owned by the security stack, and neither can be created before those buckets
# exist:
#
#   * the Config delivery channel. PutDeliveryChannel returns
#     NoSuchBucketException, "The specified Amazon S3 bucket does not exist":
#
#       https://docs.aws.amazon.com/config/latest/APIReference/API_PutDeliveryChannel.html
#
#   * the organization trail in cloudtrail.tf, which names the security
#     account's CloudTrail bucket as its destination, so that bucket and its
#     bucket policy have to exist before CloudTrail will accept the trail.
#
# The buckets are created by the security stack, and the security stack depends
# on this one. That direction is fixed and cannot be reversed: the delegated
# administrator registrations this stack owns must exist before the security
# stack can use them, so a reverse dependency would be a cycle. Note that
# Spacelift applies a dependent stack only after its dependency succeeds, so a
# failure here blocks the entire chain rather than just this stack.
#
# The consequence is that on the first apply this stack runs before the buckets
# exist. Both resources are therefore gated behind var.enable_management_account_audit,
# which defaults to false. Turning the management account's audit resources on
# is a deliberate two-step:
#
#   1. Apply this change. The security stack then creates the two buckets.
#   2. Set enable_management_account_audit = true and apply this stack again.
#
# Step 2 is a one-line change. It is separate only because the buckets these
# resources write to cannot exist before this stack has run.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  # The central Config bucket lives in the security account, declared in
  # infra/aws/security/audit-bucket-config.tf. It is a literal rather than a
  # Spacelift output reference because this stack is upstream of the security
  # stack, so referencing its output would create the reverse dependency
  # described above. Keep in sync with the security stack if it is ever renamed.
  #
  # No s3_key_prefix is set on the delivery channel, so AWS Config writes at
  # AWSLogs/<accountId>/Config/* directly under the bucket root. The bucket
  # policy grants exactly that path.
  config_bucket_name = "oconnordev-config"

  config_recorded_resource_types = [
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::KMS::Key",
    "AWS::S3::Bucket",
    "AWS::SecretsManager::Secret",
  ]
}

variable "enable_management_account_audit" {
  description = "Create the organization trail (cloudtrail.tf) and this account's Config recorder and delivery channel, both of which deliver into buckets owned by the security stack. Requires that stack to have applied once; see the apply-order note at the top of this file."
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
  count = var.enable_management_account_audit ? 1 : 0

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

output "config_recording_enabled" {
  description = "Whether the management account's Config recorder is configured and delivering to the central Config bucket."
  value       = var.enable_management_account_audit
}