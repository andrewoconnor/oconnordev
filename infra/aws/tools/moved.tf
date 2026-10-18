moved {
  from = aws_ecr_repository_policy.microsoft365_lambda_pull
  to   = aws_ecr_repository_policy.tools_images
}

moved {
  from = aws_iam_role.microsoft365_image_publisher
  to   = aws_iam_role.tools_image_publisher
}

moved {
  from = aws_iam_role_policy.microsoft365_image_publisher
  to   = aws_iam_role_policy.tools_image_publisher
}

moved {
  from = aws_cloudwatch_log_group.microsoft365[0]
  to   = aws_cloudwatch_log_group.microsoft365
}

moved {
  from = aws_iam_role_policy.microsoft365_runtime[0]
  to   = aws_iam_role_policy.microsoft365_runtime
}

moved {
  from = aws_lambda_function.microsoft365[0]
  to   = aws_lambda_function.microsoft365
}

moved {
  from = aws_lambda_function_url.microsoft365[0]
  to   = aws_lambda_function_url.microsoft365
}

moved {
  from = aws_iam_role_policy.microsoft365_gateway_invoke[0]
  to   = aws_iam_role_policy.microsoft365_gateway_invoke
}

moved {
  from = terraform_data.microsoft365_catalog[0]
  to   = terraform_data.microsoft365_catalog
}

moved {
  from = aws_bedrockagentcore_gateway_target.microsoft365[0]
  to   = aws_bedrockagentcore_gateway_target.microsoft365
}

moved {
  from = aws_iam_role_policy.gmail_target_credentials
  to   = aws_iam_role_policy.google_target_credentials
}
