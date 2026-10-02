# ---------------------------------------------------------------------------
# AWS Config recording, so the organization aggregator in the security account
# has this account's configuration to read.
#
# The recorded set is deliberately narrow. AWS Config is billed per
# configuration item recorded, so "all supported resource types" in every
# account is what turns a sub-dollar line item into a monthly bill; this is the
# set this account actually deploys.
#
# Delivery goes to the central Config bucket in the security account, the same
# bucket GENERAL, PRODUCTION and SECURITY write to. That bucket is declared in
# infra/aws/security/audit-bucket-config.tf. The per-account bucket this stack
# used to create (oconnordev-config-421680664125) has been removed.
#
# This is the change that makes "how is this resource configured, and when did
# it change" answerable from the security account without any cross-account
# credential in the reader.
# ---------------------------------------------------------------------------

locals {
  # The central Config bucket lives in the security account. It is a literal
  # rather than a Spacelift output reference because the same name is needed by
  # four stacks, and threading a per-stack reference through each one would make
  # the name change ripple through four sets of state for no benefit. Keep in
  # sync with the security stack if it is ever renamed.
  config_bucket_name = "oconnordev-config"

  config_recorded_resource_types = [
    "AWS::Cognito::UserPool",
    "AWS::IAM::Policy",
    "AWS::IAM::Role",
    "AWS::KMS::Key",
    "AWS::Lambda::Function",
    "AWS::S3::Bucket",
    "AWS::SecretsManager::Secret",
  ]
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
  role       = aws_iam_role.config_recorder.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_config_configuration_recorder" "hermes" {
  # checkov:skip=CKV2_AWS_48:Deliberate. This check wants the recorder to record every possible resource type, which is exactly the configuration this design exists to avoid -- AWS Config is billed per configuration item recorded. The recording group lists the resource types this organization actually deploys.
  name     = "default"
  role_arn = aws_iam_role.config_recorder.arn

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

resource "aws_config_delivery_channel" "hermes" {
  name           = "default"
  s3_bucket_name = local.config_bucket_name

  # The bucket lives in the security account and already exists by the time this
  # stack runs: the Spacelift dependency chain is
  # general -> security -> hermes -> production, so the stack that creates the
  # bucket has completed before this one starts.
  depends_on = [aws_config_configuration_recorder.hermes]
}

resource "aws_config_configuration_recorder_status" "hermes" {
  # checkov:skip=CKV2_AWS_45:Deliberate. Recording every supported resource type is the configuration that makes this account expensive -- AWS Config is billed per configuration item recorded. The recording group in this stack lists the resource types this organization actually deploys; recording all supported types is the opposite of the intent of this change.
  name       = aws_config_configuration_recorder.hermes.name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.hermes]
}