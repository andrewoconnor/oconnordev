# ---------------------------------------------------------------------------
# AWS Config in the security account.
#
# The recorder in this file is scoped to the security account's own resources.
# What makes the account the organization's read vantage point is the
# organization aggregator at the bottom, which reads the configuration history
# that every other account's own recorder produces. The aggregator is empty
# until the source accounts record something, so this stack is inert until
# infra/aws/production and infra/aws/hermes have their own recorders.
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

resource "aws_iam_role_policy_attachment" "config_recorder" {
  role       = aws_iam_role.config_recorder.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_s3_bucket" "config" {
  # checkov:skip=CKV_AWS_18:Access logging would need a second bucket and a log-delivery policy. This bucket holds Config's own configuration history and snapshots; nothing consumes access logs for it.
  # checkov:skip=CKV_AWS_144:Cross-region replication would need a replica bucket and a replication role in a second Region. Everything in this organization is us-east-1.
  # checkov:skip=CKV2_AWS_62:Event notifications need a consumer. Nothing subscribes to object-created events on the Config history bucket; Config delivers to it directly.
  # checkov:skip=CKV_AWS_145:SSE-KMS would need a customer-managed key whose policy grants the Config recorder role kms:Decrypt and kms:GenerateDataKey. The AWS-managed aws/s3 key cannot be edited to add that grant, so a CMK here is a new key plus a policy, not a one-line change. SSE-S3 (AES256) is the current state of the two static-site buckets as well; moving both to CMKs is one decision, not two.
  bucket = local.config_delivery_bucket_name
}

resource "aws_s3_bucket_public_access_block" "config" {
  bucket = aws_s3_bucket.config.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "config" {
  bucket = aws_s3_bucket.config.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "config" {
  bucket = aws_s3_bucket.config.id

  # Versioning is on so a bad write to configuration history can be rolled
  # back; the rule below keeps that from accumulating storage unbounded.
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  depends_on = [aws_s3_bucket_versioning.config]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "config" {
  bucket = aws_s3_bucket.config.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "config_bucket" {
  statement {
    sid    = "ConfigBucketAcl"
    effect = "Allow"

    actions = [
      "s3:GetBucketAcl",
      "s3:ListBucket",
    ]

    resources = [aws_s3_bucket.config.arn]

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

  statement {
    sid    = "ConfigBucketWrite"
    effect = "Allow"

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.config.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_s3_bucket_policy" "config" {
  bucket = aws_s3_bucket.config.id
  policy = data.aws_iam_policy_document.config_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.config]
}

resource "aws_config_configuration_recorder" "security" {
  name     = "default"
  role_arn = aws_iam_role.config_recorder.arn

  recording_group {
    all_supported = false

    # The recorded set includes IAM roles and policies, which are global
    # resource types. They are only recorded when this is true, and only in one
    # Region per account; every stack in this organization is us-east-1.
    include_global_resource_types = true
    resource_types                = local.config_recorded_resource_types
  }
}

resource "aws_config_delivery_channel" "security" {
  name           = "default"
  s3_bucket_name = aws_s3_bucket.config.bucket

  depends_on = [aws_config_configuration_recorder.security]
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
