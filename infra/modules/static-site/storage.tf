data "aws_iam_policy_document" "web_tls" {
  statement {
    sid = "Enforce TLS"

    effect = "Deny"

    actions = [
      "s3:*"
    ]

    resources = [
      aws_s3_bucket.web.arn,
      "${aws_s3_bucket.web.arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }

    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }

  statement {
    sid = "AllowCloudFrontServicePrincipal"

    effect = "Allow"

    actions = [
      "s3:GetObject"
    ]

    resources = [
      "${aws_s3_bucket.web.arn}/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
  }
}

resource "aws_s3_bucket" "web" {
  # checkov:skip=CKV_AWS_18:Access logs need a second bucket and incur request/storage cost; they do not back up external image bytes. Logging is not justified for these personal static sites; recovery risks are documented separately.
  # checkov:skip=CKV_AWS_144:No paid replication by owner cost choice. External images have incomplete provenance and are NOT reproducible; versioning only retains overwritten/deleted versions for 30 days. Regional/account loss and older version loss remain accepted risks. See docs/runbooks/drumrollworld-image-recovery.md.
  # checkov:skip=CKV_AWS_145:CloudFront reaches this bucket through an origin access control. An SSE-KMS bucket can only be read by CloudFront if a customer-managed key's policy grants the CloudFront service principal decrypt, and the AWS-managed aws/s3 key policy cannot be edited -- so SSE-KMS here would break the distribution rather than harden the bucket. SSE-S3 (AES256) is applied by aws_s3_bucket_server_side_encryption_configuration.web.
  # checkov:skip=CKV2_AWS_62:Event notifications need a consumer. Nothing consumes object-created events for this bucket; notifications would target a queue or function with no work to do.
  bucket = var.bucket_name

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = var.bucket_name
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.web]
}

resource "aws_s3_bucket_policy" "web_tls" {
  bucket = aws_s3_bucket.web.id

  policy = data.aws_iam_policy_document.web_tls.json
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket = aws_s3_bucket.web.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id

  versioning_configuration {
    status = "Enabled"
  }
}