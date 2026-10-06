locals {
  general_account_id        = local.accounts["GENERAL"]
  security_account_id       = local.accounts["SECURITY"]
  security_gateway_role_arn = "arn:aws:iam::${local.security_account_id}:role/oconnordev-security-gateway"
  cur_schema                = jsondecode(file("${path.module}/../cost-export-schema.json"))
  cur_columns               = [for column in local.cur_schema.columns : column.name]
  export_bucket_name        = "oconnordev-org-cost-usage"
  export_name               = "oconnordev-org-cost-usage"
  export_data_location      = "s3://${local.export_bucket_name}/billing/${local.export_name}/data/"
}

resource "aws_s3_bucket" "org_cost_usage" {
  # checkov:skip=CKV_AWS_18:Access logging would need another bucket and delivery policy; no log consumer is in scope.
  # checkov:skip=CKV2_AWS_62:No event-driven consumer for delivered CUR objects.
  # checkov:skip=CKV_AWS_144:No cross-region recovery requirement; replication would add recurring charges.
  # checkov:skip=CKV_AWS_145:SSE-S3 is explicitly required and the existing execution role denies KMS decrypt.
  bucket        = local.export_bucket_name
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}
resource "aws_s3_bucket_public_access_block" "org_cost_usage" {
  bucket                  = aws_s3_bucket.org_cost_usage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "org_cost_usage" {
  bucket = aws_s3_bucket.org_cost_usage.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "org_cost_usage" {
  bucket = aws_s3_bucket.org_cost_usage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_versioning" "org_cost_usage" {
  bucket = aws_s3_bucket.org_cost_usage.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "org_cost_usage" {
  # checkov:skip=CKV_AWS_300:Incomplete uploads are aborted below; current billing objects are retained indefinitely.
  bucket = aws_s3_bucket.org_cost_usage.id
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {
      prefix = "billing/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {
      prefix = "billing/"
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
data "aws_iam_policy_document" "org_cost_usage" {
  statement {
    sid     = "AllowDataExportsDelivery"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    principals {
      type        = "Service"
      identifiers = ["bcm-data-exports.amazonaws.com"]
    }
    resources = ["${aws_s3_bucket.org_cost_usage.arn}/billing/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.general_account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bcm-data-exports:us-east-1:${local.general_account_id}:export/*"]
    }
  }
  statement {
    sid     = "AllowSecurityGatewayReadCur"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    principals {
      type        = "AWS"
      identifiers = [local.security_gateway_role_arn]
    }
    resources = ["${aws_s3_bucket.org_cost_usage.arn}/billing/${local.export_name}/data/*"]
  }
  statement {
    sid     = "AllowSecurityGatewayListCur"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    principals {
      type        = "AWS"
      identifiers = [local.security_gateway_role_arn]
    }
    resources = [aws_s3_bucket.org_cost_usage.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["billing/${local.export_name}/data", "billing/${local.export_name}/data/*"]
    }
  }
  statement {
    sid     = "AllowSecurityGatewayGetBucketLocation"
    effect  = "Allow"
    actions = ["s3:GetBucketLocation"]
    principals {
      type        = "AWS"
      identifiers = [local.security_gateway_role_arn]
    }
    resources = [aws_s3_bucket.org_cost_usage.arn]
  }
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = [aws_s3_bucket.org_cost_usage.arn, "${aws_s3_bucket.org_cost_usage.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
  statement {
    sid     = "DenyBucketDeletion"
    effect  = "Deny"
    actions = ["s3:DeleteBucket"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    resources = [aws_s3_bucket.org_cost_usage.arn]
  }
}
resource "aws_s3_bucket_policy" "org_cost_usage" {
  bucket     = aws_s3_bucket.org_cost_usage.id
  policy     = data.aws_iam_policy_document.org_cost_usage.json
  depends_on = [aws_s3_bucket_public_access_block.org_cost_usage, aws_s3_bucket_ownership_controls.org_cost_usage]
}
resource "aws_bcmdataexports_export" "org_cost_usage" {
  export {
    name = local.export_name
    data_query {
      query_statement = "SELECT ${join(", ", local.cur_columns)} FROM COST_AND_USAGE_REPORT"
      table_configurations = {
        COST_AND_USAGE_REPORT = {
          TIME_GRANULARITY                   = "DAILY"
          INCLUDE_RESOURCES                  = "TRUE"
          INCLUDE_SPLIT_COST_ALLOCATION_DATA = "FALSE"
        }
      }
    }
    destination_configurations {
      s3_destination {
        s3_bucket = aws_s3_bucket.org_cost_usage.id
        s3_prefix = "billing"
        s3_region = "us-east-1"
        s3_output_configurations {
          compression = "PARQUET"
          format      = "PARQUET"
          output_type = "CUSTOM"
          overwrite   = "OVERWRITE_REPORT"
        }
      }
    }
    refresh_cadence {
      frequency = "SYNCHRONOUS"
    }
  }
  depends_on = [aws_s3_bucket_policy.org_cost_usage]
}
output "cost_export_arn" {
  value = aws_bcmdataexports_export.org_cost_usage.arn
}
output "cost_export_bucket_name" {
  value = aws_s3_bucket.org_cost_usage.id
}
output "cost_export_data_location" {
  value = local.export_data_location
}
