# Shared analytics workgroup. Keeping the resource address unchanged makes
# this a file-only refactor: no state move or replacement is required.
resource "aws_athena_workgroup" "hermes_analytics" {
  name          = "hermes-analytics"
  description   = "Bounded reusable Athena workgroup for Hermes billing analysis."
  force_destroy = false
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff_per_query
    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
    result_configuration {
      output_location       = "s3://${aws_s3_bucket.athena_results.id}/${local.analytics_results_prefix}"
      expected_bucket_owner = local.accounts["SECURITY"]
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
  depends_on = [aws_s3_bucket_policy.athena_results]
}
