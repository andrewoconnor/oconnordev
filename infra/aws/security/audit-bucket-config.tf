
locals {
  config_source_account_ids = [
    local.accounts["GENERAL"],
    local.accounts["PRODUCTION"],
    local.accounts["HERMES"],
    data.aws_caller_identity.current.account_id,
  ]

  config_recorder_role_arns = [
    for account_id in local.config_source_account_ids :
    "arn:${data.aws_partition.current.partition}:iam::${account_id}:role/oconnordev-config-recorder"
  ]

  config_source_account_roots = [
    for account_id in local.config_source_account_ids :
    "arn:${data.aws_partition.current.partition}:iam::${account_id}:root"
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

  statement {
    sid    = "AWSConfigRecorderRoleExistenceCheck"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = local.config_source_account_roots
    }

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.config.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = local.config_recorder_role_arns
    }
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
      "${aws_s3_bucket.config.arn}/AWSLogs/${account_id}/Config/*"
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
