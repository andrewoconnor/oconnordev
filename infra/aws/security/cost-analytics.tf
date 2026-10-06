locals {
  analytics_results_name   = "oconnordev-athena-results-${local.accounts["SECURITY"]}"
  analytics_results_prefix = "hermes-analytics/"
  cost_export_bucket_name  = var.cost_export_bucket_name != "" ? var.cost_export_bucket_name : "oconnordev-org-cost-usage-${local.accounts["GENERAL"]}"
  cost_export_name         = "oconnordev-org-cost-usage"
  cost_export_data_root    = var.cost_export_data_location != "" ? var.cost_export_data_location : "s3://${local.cost_export_bucket_name}/billing/${local.cost_export_name}/data/"
  cost_export_columns      = jsondecode(file("${path.module}/../cost-export-schema.json")).columns
  athena_workgroup_arn     = "arn:aws:athena:us-east-1:${local.accounts["SECURITY"]}:workgroup/hermes-analytics"
  glue_catalog_arn         = "arn:aws:glue:us-east-1:${local.accounts["SECURITY"]}:catalog"
  glue_database_arn        = "arn:aws:glue:us-east-1:${local.accounts["SECURITY"]}:database/org_billing"
  glue_table_arn           = "arn:aws:glue:us-east-1:${local.accounts["SECURITY"]}:table/org_billing/cost_usage"
}

resource "aws_s3_bucket" "athena_results" {
  # checkov:skip=CKV_AWS_18:Server access logs would require a separate log bucket and delivery policy, with no stated consumer of these query outputs.
  # checkov:skip=CKV_AWS_144:This one-region workgroup has no stated cross-region recovery need; replication adds recurring cost.
  # checkov:skip=CKV2_AWS_62:No event consumer uses query-result notifications.
  # checkov:skip=CKV_AWS_145:SSE-S3 is intentional and compatible with the gateway KMS-decrypt deny.
  bucket        = local.analytics_results_name
  force_destroy = false
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket                  = aws_s3_bucket.athena_results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
    blocked_encryption_types = ["SSE-C"]
  }
}
resource "aws_s3_bucket_versioning" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  # checkov:skip=CKV_AWS_300:This only cleans query results and aborts incomplete uploads; not source data.
  bucket = aws_s3_bucket.athena_results.id
  rule {
    id     = "expire-query-results"
    status = "Enabled"
    filter { prefix = local.analytics_results_prefix }
    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
  rule {
    id     = "abort-incomplete-query-uploads"
    status = "Enabled"
    filter { prefix = local.analytics_results_prefix }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}
data "aws_iam_policy_document" "athena_results" {
  statement {
    sid = "DenyInsecureTransport"
    effect = "Deny"
    actions = ["s3:*"]
    resources = [aws_s3_bucket.athena_results.arn, "${aws_s3_bucket.athena_results.arn}/*"]
    principals { type = "AWS" identifiers = ["*"] }
    condition { test = "Bool" variable = "aws:SecureTransport" values = ["false"] }
  }
  statement {
    sid = "DenyBucketDeletion"
    effect = "Deny"
    actions = ["s3:DeleteBucket"]
    resources = [aws_s3_bucket.athena_results.arn]
    principals { type = "AWS" identifiers = ["*"] }
  }
}
resource "aws_s3_bucket_policy" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  policy = data.aws_iam_policy_document.athena_results.json
  depends_on = [aws_s3_bucket_public_access_block.athena_results, aws_s3_bucket_ownership_controls.athena_results]
}
resource "aws_athena_workgroup" "hermes_analytics" {
  name = "hermes-analytics"
  description = "Bounded, reusable Athena workgroup for Hermes cost and usage analysis."
  force_destroy = false
  configuration {
    enforce_workgroup_configuration = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query = var.athena_bytes_scanned_cutoff_per_query
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.id}/${local.analytics_results_prefix}"
      expected_bucket_owner = local.accounts["SECURITY"]
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
  depends_on = [aws_s3_bucket_policy.athena_results]
}
resource "aws_glue_catalog_database" "org_billing" {
  name = "org_billing"
  description = "Organization CUR 2.0 cost and usage data."
}
resource "aws_glue_catalog_table" "cost_usage" {
  name = "cost_usage"
  database_name = aws_glue_catalog_database.org_billing.name
  table_type = "EXTERNAL_TABLE"
  parameters = {
    classification = "parquet"
    EXTERNAL = "TRUE"
    "projection.enabled" = "true"
    "projection.billing_period.type" = "date"
    "projection.billing_period.format" = "yyyy-MM"
    "projection.billing_period.interval" = "1"
    "projection.billing_period.interval.unit" = "MONTHS"
    "projection.billing_period.range" = "${var.cost_export_projection_start_month},NOW"
    "storage.location.template" = "${trimsuffix(local.cost_export_data_root, "/")}/BILLING_PERIOD=$${billing_period}/"
  }
  partition_keys {
    name = "billing_period"
    type = "string"
  }
  storage_descriptor {
    location = local.cost_export_data_root
    input_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    compressed = true
    dynamic "columns" {
      for_each = local.cost_export_columns
      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
    ser_de_info {
      name = "ParquetHiveSerDe"
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }
  }
}
output "athena_results_bucket_name" { value = aws_s3_bucket.athena_results.id }
output "athena_workgroup_name" { value = aws_athena_workgroup.hermes_analytics.name }
output "billing_database_name" { value = aws_glue_catalog_database.org_billing.name }
output "billing_table_name" { value = aws_glue_catalog_table.cost_usage.name }
