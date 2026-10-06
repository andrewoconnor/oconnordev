resource "aws_iam_role_policy" "security_gateway_athena_analytics" {
  name = "oconnordev-security-gateway-athena-analytics"
  role = aws_iam_role.security_gateway.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "QueryNamedWorkgroup", Effect = "Allow", Action = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"], Resource = local.athena_workgroup_arn },
      { Sid = "ReadBillingCatalogMetadata", Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables"], Resource = [local.glue_catalog_arn, local.glue_database_arn, local.glue_table_arn] },
      { Sid = "ReadCurExportObjects", Effect = "Allow", Action = ["s3:GetObject"], Resource = "arn:aws:s3:::${local.cost_export_bucket_name}/billing/${local.cost_export_name}/data/*" },
      { Sid = "ListCurExportPrefix", Effect = "Allow", Action = ["s3:ListBucket"], Resource = "arn:aws:s3:::${local.cost_export_bucket_name}", Condition = { StringLike = { "s3:prefix" = ["billing/${local.cost_export_name}/data", "billing/${local.cost_export_name}/data/*"] } } },
      { Sid = "GetCurBucketLocation", Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = "arn:aws:s3:::${local.cost_export_bucket_name}" },
      { Sid = "ReadAndWriteAthenaResults", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"], Resource = "${aws_s3_bucket.athena_results.arn}/${local.analytics_results_prefix}*" },
      { Sid = "ListAthenaResultsPrefix", Effect = "Allow", Action = ["s3:ListBucket", "s3:ListBucketMultipartUploads"], Resource = aws_s3_bucket.athena_results.arn, Condition = { StringLike = { "s3:prefix" = [local.analytics_results_prefix, "${local.analytics_results_prefix}*"] } } },
      { Sid = "GetAthenaResultsBucketLocation", Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = aws_s3_bucket.athena_results.arn }
    ]
  })
}
