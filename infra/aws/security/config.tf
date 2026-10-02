# ---------------------------------------------------------------------------
# AWS Config in the security account.
#
# The recorder here is scoped to this account's own resources. What makes this
# account the organization's read vantage point is the organization aggregator
# at the bottom of this file, which reads the configuration history that every
# account's own recorder produces.
#
# Delivery goes to the central Config bucket, oconnordev-config, declared in
# audit-bucket-config.tf. The per-account bucket this stack used to create
# (oconnordev-config-482921124454) has been removed: all four accounts deliver
# to the one central bucket now.
#
# Creating an organization aggregator requires this account to be a registered
# delegated administrator for config.amazonaws.com. That registration lives in
# the management account (infra/aws/general/security-delegation.tf) and must be
# applied first.
# ---------------------------------------------------------------------------

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

resource "aws_config_configuration_recorder" "security" {
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

resource "aws_config_delivery_channel" "security" {
  name           = "default"
  s3_bucket_name = local.config_bucket_name
  s3_key_prefix  = local.config_key_prefix

  # The bucket policy must exist before recording starts: AWS Config verifies
  # that the bucket is writable when the recorder is enabled, and a delivery
  # channel pointed at a bucket whose policy does not yet permit Config writes
  # fails that check.
  depends_on = [
    aws_config_configuration_recorder.security,
    aws_s3_bucket_policy.config,
  ]
}

resource "aws_config_configuration_recorder_status" "security" {
  # checkov:skip=CKV2_AWS_45:Deliberate. Recording every supported resource type is the configuration that makes this account expensive -- AWS Config is billed per configuration item recorded. The recording group in this stack lists the resource types this organization actually deploys; recording all supported types is the opposite of the intent of this change.
  name       = aws_config_configuration_recorder.security.name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.security]
}

# ---------------------------------------------------------------------------
# Organization aggregator: the read vantage point.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "config_aggregator_assume_role" {
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

resource "aws_iam_role" "config_aggregator" {
  name               = "oconnordev-config-aggregator"
  assume_role_policy = data.aws_iam_policy_document.config_aggregator_assume_role.json
}

resource "aws_iam_role_policy_attachment" "config_aggregator" {
  role       = aws_iam_role.config_aggregator.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSConfigRoleForOrganizations"
}

resource "aws_config_configuration_aggregator" "organization" {
  name = "oconnordev-organization"

  organization_aggregation_source {
    all_regions = true
    role_arn    = aws_iam_role.config_aggregator.arn
  }

  depends_on = [aws_iam_role_policy_attachment.config_aggregator]
}

output "config_aggregator_name" {
  description = "Name of the organization-wide Config aggregator."
  value       = aws_config_configuration_aggregator.organization.name
}
