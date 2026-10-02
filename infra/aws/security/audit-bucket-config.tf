# ---------------------------------------------------------------------------
# oconnordev-config -- Config history and snapshots from all four accounts.
#
# Cross-account delivery is why this policy is longer than a same-account one
# would be. Config in GENERAL, PRODUCTION and HERMES writes here, which AWS
# documents as requiring both a service-principal grant and a grant to each
# recorder's IAM role:
#
#   https://docs.aws.amazon.com/config/latest/developerguide/s3-bucket-policy.html
#   "The IAM role you assign to the configuration recorder needs explicit
#    permission to perform the s3:ListBucket operation. This is because AWS
#    Config calls the Amazon S3 HeadBucket API with this IAM role to determine
#    the bucket location."
#   "The S3 bucket policy must include permissions for the IAM role assigned to
#    the configuration recorder."
#
# The recorder roles themselves need no extra inline permission: the managed
# policy they already carry, service-role/AWS_ConfigRole, grants s3:ListBucket on
# every resource. The delivery writes are made by the Config service principal,
# not by the recorder role.
#
# The delivery path is <prefix>/AWSLogs/<sourceAccountId>/Config/*, which is why
# the delivery resources below are built per source account rather than
# wildcarded.
#
# Like the CloudTrail bucket, this one grants this account's own principals no
# read access in its policy: same-account identity policy already covers the
# account administrators and the security gateway role. No Object Lock here
# either; see the note in audit-bucket-cloudtrail.tf.
# ---------------------------------------------------------------------------

locals {
  # Every account that delivers into this bucket, and the recorder role each one
  # uses. The role name is fixed by the four config.tf files; it is repeated
  # rather than looked up because three of the four live in other accounts.
  config_source_account_ids = [
    "905418422177", # GENERAL
    "767397796791", # PRODUCTION
    "421680664125", # HERMES
    "482921124454", # SECURITY, this account
  ]

  config_recorder_role_arns = [
    for account_id in local.config_source_account_ids :
    "arn:${data.aws_partition.current.partition}:iam::${account_id}:role/oconnordev-config-recorder"
  ]
}

resource "aws_s3_bucket" "config" {
  # checkov:skip=CKV_AWS_18:Access logging would need a second bucket plus a log-delivery policy and grant. Nothing consumes access logs for the Config history bucket; Config delivers to it directly.
  # checkov:skip=CKV_AWS_144:Cross-region replication would need a replica bucket and a replication role in a second Region. Everything in this organization is us-east-1.
  # checkov:skip=CKV2_AWS_62:Event notifications need a consumer. Nothing subscribes to object-created events on the Config history bucket.
  # checkov:skip=CKV_AWS_145:SSE-KMS would add a customer-managed key plus a per-request KMS charge and require kms:Decrypt/GenerateDataKey grants for Config in the bucket policy. SSE-S3 (AES256) is what the per-account Config buckets used before this change.
  bucket = local.config_bucket_name
}

resource "aws_s3_bucket_public_access_block" "config" {
  bucket = aws_s3_bucket.config.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "config" {
  bucket = aws_s3_bucket.config.id

  # Disables ACLs entirely. Three other accounts write here, so object ownership
  # matters: under BucketOwnerEnforced every object is owned by this account
  # regardless of which account it came from. Config passes
  # s3:x-amz-acl bucket-owner-full-control, which S3 accepts as a no-op under
  # this setting, and the bucket policy still conditions on that header.
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "config" {
  bucket = aws_s3_bucket.config.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "config" {
  bucket = aws_s3_bucket.config.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    blocked_encryption_types = ["SSE-C"]
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "config" {
  bucket = aws_s3_bucket.config.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Versioning is on so a bad write to configuration history can be rolled back;
  # this keeps that from accumulating storage unbounded. Config rewrites the same
  # object paths as resources change, so noncurrent versions are the expected
  # case here rather than an exception.
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

data "aws_iam_policy_document" "config_bucket" {
  statement {
    sid    = "AWSConfigBucketPermissionsCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.config.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = local.config_source_account_ids
    }
  }

  statement {
    sid    = "AWSConfigBucketExistenceCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.config.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = local.config_source_account_ids
    }
  }

  # The cross-account HeadBucket check is made with each recorder's own IAM role,
  # not with the Config service principal, so the roles need their own grant.
  statement {
    sid    = "AWSConfigRecorderRoleExistenceCheck"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = local.config_recorder_role_arns
    }

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.config.arn]
  }

  statement {
    sid    = "AWSConfigBucketDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    actions = ["s3:PutObject"]
    resources = [
      for account_id in local.config_source_account_ids :
      "${aws_s3_bucket.config.arn}/${local.config_key_prefix}/AWSLogs/${account_id}/Config/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = local.config_source_account_ids
    }
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.config.arn,
      "${aws_s3_bucket.config.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Deletion protection, as on the CloudTrail bucket: an intentional teardown
  # must remove this statement first.
  statement {
    sid    = "DenyBucketDeletion"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions   = ["s3:DeleteBucket"]
    resources = [aws_s3_bucket.config.arn]
  }
}

resource "aws_s3_bucket_policy" "config" {
  bucket = aws_s3_bucket.config.id
  policy = data.aws_iam_policy_document.config_bucket.json

  depends_on = [
    aws_s3_bucket_public_access_block.config,
    aws_s3_bucket_ownership_controls.config,
    aws_s3_bucket_versioning.config,
  ]
}

output "config_audit_bucket_name" {
  description = "Name of the central Config bucket. Delivery channels in GENERAL, PRODUCTION and HERMES point at this name."
  value       = aws_s3_bucket.config.id
}

output "config_audit_bucket_arn" {
  description = "ARN of the central Config bucket."
  value       = aws_s3_bucket.config.arn
}
