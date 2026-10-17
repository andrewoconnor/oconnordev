run "enabled_boundary" {
  command = plan
  variables {
    thundermail_runtime_enabled = true
    thundermail_image_digest    = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    thundermail_secret_arn      = "arn:aws:secretsmanager:us-east-1:421680664125:secret:/hermes/thundermail/app-password-abc123"
  }
  assert {
    condition     = length(aws_iam_role.thundermail) == 1 && length(aws_lambda_function.thundermail) == 1 && length(aws_cloudwatch_log_group.thundermail) == 1 && length(aws_iam_role_policy.thundermail_runtime) == 1 && length(aws_iam_role_policy.thundermail_gateway_invoke) == 1 && length(terraform_data.thundermail_catalog) == 1 && length(aws_bedrockagentcore_gateway_target.thundermail) == 1 && length(aws_bedrockagentcore_policy.thundermail_read) == 3
    error_message = "All native runtime/target/grants/catalog/permits enabled together."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.thundermail_gateway_invoke[0].policy).Statement[0].Action == ["lambda:InvokeFunction"] && jsondecode(aws_iam_role_policy.thundermail_gateway_invoke[0].policy).Statement[0].Resource == [local.thundermail_function_arn]
    error_message = "Gateway gets exact function invoke only, no secret/URL grants."
  }
  assert {
    condition     = length(jsondecode(aws_iam_role_policy.thundermail_runtime[0].policy).Statement) == 2 && jsondecode(aws_iam_role_policy.thundermail_runtime[0].policy).Statement[0].Action == ["secretsmanager:GetSecretValue"] && jsondecode(aws_iam_role_policy.thundermail_runtime[0].policy).Statement[0].Resource == [var.thundermail_secret_arn]
    error_message = "Runtime gets exact secret read, no write."
  }
  assert {
    condition     = aws_lambda_function.thundermail[0].architectures == tolist(["arm64"]) && aws_lambda_function.thundermail[0].package_type == "Image" && aws_lambda_function.thundermail[0].environment[0].variables.THUNDERMAIL_CREDENTIAL_SECRET_ARN == var.thundermail_secret_arn && length(aws_bedrockagentcore_gateway_target.thundermail[0].target_configuration[0].mcp[0].lambda[0].tool_schema[0].inline_payload) == 3
    error_message = "Native single ARM64 Lambda and inline three tools, not HTTP."
  }
  assert {
    condition     = toset(jsondecode(aws_ecr_repository_policy.microsoft365_lambda_pull.policy).Statement[0].Condition.ArnLike["aws:SourceArn"]) == toset([local.microsoft365_function_arn, local.thundermail_function_arn])
    error_message = "Extend existing shared pull grant only by the exact Thundermail ARN."
  }
}
