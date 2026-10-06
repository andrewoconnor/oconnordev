locals {
  cost_export_schema        = jsondecode(file("${path.module}/../cost-export-schema.json"))
  cost_export_columns       = [for column in local.cost_export_schema.columns : column.name]
  cost_export_query         = "SELECT ${join(", ", local.cost_export_columns)} FROM COST_AND_USAGE_REPORT"
  cost_export_bucket        = "oconnordev-org-cost-usage-${local.accounts["GENERAL"]}"
  cost_export_name          = "oconnordev-org-cost-usage"
  security_gateway_role_arn = "arn:aws:iam::${local.accounts["SECURITY"]}:role/oconnordev-security-gateway"
}

resource "aws_s3_bucket" "org_cost_usage" {
  # checkov:skip=CKV_AWS_18:Server access logs would require a second bucket and a log-delivery policy; this dedicated billing destination has no access-log consumer.
  # checkov:skip=CKV_AWS_144:All components use us-east-1; replication adds ongoing storage and request charges without a regional recovery requirement.
  # checkov:skip=CKV2_AWS_62:There is no event consumer for billing objects; a notification target would add unneeded infrastructure.
  # checkov:skip=CKV_AWS_145:SSE-S3 is explicitly required here and avoids KMS charges; the gateway role also retains its explicit KMS decrypt deny.
  bucket        = local.cost_export_bucket
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
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "org_cost_usage" {
  bucket = aws_s3_bucket.org_cost_usage.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
    blocked_encryption_types = ["SSE-C"]
  }
}

resource "aws_s3_bucket_versioning" "org_cost_usage" {
  bucket = aws_s3_bucket.org_cost_usage.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "org_cost_usage" {
  bucket = aws_s3_bucket.org_cost_usage.id
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

data "aws_iam_policy_document" "org_cost_usage_bucket" {
  statement {
    sid       = "DataExportsDelivery"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.org_cost_usage.arn}/billing/*"]
    principals {
      type        = "Service"
      identifiers = ["bcm-data-exports.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.accounts["GENERAL"]]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bcm-data-exports:us-east-1:${local.accounts["GENERAL"]}:export/*"]
    }
  }
  statement {
    sid       = "AllowSecurityGatewayReadBillingObjects"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.org_cost_usage.arn}/billing/${local.cost_export_name}/data/*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.accounts["SECURITY"]}:root"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [local.security_gateway_role_arn]
    }
  }
  statement {
    sid       = "AllowSecurityGatewayListBillingPrefix"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.org_cost_usage.arn]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.accounts["SECURITY"]}:root"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [local.security_gateway_role_arn]
    }
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["billing/${local.cost_export_name}/data", "billing/${local.cost_export_name}/data/*"]
    }
  }
  statement {
    sid       = "AllowSecurityGatewayGetBucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.org_cost_usage.arn]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.accounts["SECURITY"]}:root"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [local.security_gateway_role_arn]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.org_cost_usage.arn, "${aws_s3_bucket.org_cost_usage.arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
  statement {
    sid       = "DenyBucketDeletion"
    effect    = "Deny"
    actions   = ["s3:DeleteBucket"]
    resources = [aws_s3_bucket.org_cost_usage.arn]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
  }
}

resource "aws_s3_bucket_policy" "org_cost_usage" {
  bucket     = aws_s3_bucket.org_cost_usage.id
  policy     = data.aws_iam_policy_document.org_cost_usage_bucket.json
  depends_on = [aws_s3_bucket_public_access_block.org_cost_usage, aws_s3_bucket_ownership_controls.org_cost_usage]
}

resource "aws_bcmdataexports_export" "org_cost_usage" {
  export {
    name = local.cost_export_name
    data_query {
      query_statement = local.cost_export_query
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
    refresh_cadence { frequency = "SYNCHRONOUS" }
  }
  depends_on = [aws_s3_bucket_policy.org_cost_usage]
}

output "cost_export_arn" {
  value       = aws_bcmdataexports_export.org_cost_usage.arn
  description = "ARN of the organization CUR 2.0 export."
}
output "cost_export_bucket_name" {
  value       = aws_s3_bucket.org_cost_usage.id
  description = "GENERAL-owned bucket containing the CUR 2.0 export."
}
output "cost_export_data_location" {
  value       = "s3://${aws_s3_bucket.org_cost_usage.id}/billing/${local.cost_export_name}/data/"
  description = "CUR 2.0 Parquet data root (not metadata or manifests)."
}
