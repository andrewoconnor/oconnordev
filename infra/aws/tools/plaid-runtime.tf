locals {
  plaid_function_name = "hermes-plaid"
  plaid_tool_schemas  = jsondecode(file("${path.module}/lambdas/plaid/tools.json")).tools
}

resource "aws_secretsmanager_secret" "plaid" {
  # checkov:skip=CKV_AWS_149:The AWS-managed Secrets Manager key encrypts this owner-only credential container.
  # checkov:skip=CKV2_AWS_57:Existing Plaid Item tokens are owner-managed; automatic rotation is not supported by this read-only runtime.
  name                    = "/hermes/plaid/credentials"
  description             = "Owner-managed Plaid production client and existing Item credentials."
  recovery_window_in_days = 30
}

data "archive_file" "plaid" {
  type        = "zip"
  source_dir  = "${local.repo_root}/infra/aws/tools/lambdas/plaid"
  output_path = "${path.module}/.terraform-archives/plaid.zip"
  excludes    = ["tools.json", "test_*.py", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "plaid" {
  # checkov:skip=CKV_AWS_158:Encrypted with the default AWS-owned key; the runtime emits no payload or credential logs.
  # checkov:skip=CKV_AWS_338:Fourteen-day retention bounds operational logs, not an audit trail.
  name              = "/aws/lambda/${local.plaid_function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "plaid" {
  name = local.plaid_function_name
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "plaid" {
  name = "plaid-own-secret-and-logs"
  role = aws_iam_role.plaid.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.plaid.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.plaid.arn}:*"] }
    ]
  })
}

resource "aws_lambda_function" "plaid" {
  # checkov:skip=CKV_AWS_116:Synchronous native gateway calls have no asynchronous retry queue.
  # checkov:skip=CKV_AWS_117:Public Secrets Manager and Plaid HTTPS need no VPC or NAT.
  # checkov:skip=CKV_AWS_173:Environment contains only the Secrets Manager ARN, never credential values.
  # checkov:skip=CKV_AWS_272:Repository archive and source_code_hash bind the Python ZIP; account code signing is not configured.
  # checkov:skip=CKV_AWS_50:The runtime performs one bounded read POST; tracing would add no useful diagnostics.
  function_name                  = local.plaid_function_name
  role                           = aws_iam_role.plaid.arn
  handler                        = "plaid.handler"
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  timeout                        = 14
  memory_size                    = 128
  reserved_concurrent_executions = 2
  filename                       = data.archive_file.plaid.output_path
  source_code_hash               = data.archive_file.plaid.output_base64sha256

  environment {
    variables = { SECRETS_ARN = aws_secretsmanager_secret.plaid.arn }
  }

  depends_on = [aws_cloudwatch_log_group.plaid, aws_iam_role_policy.plaid]
}

resource "aws_iam_role_policy" "plaid_gateway_invoke" {
  name = "plaid-native-invoke-only"
  role = aws_iam_role.hermes_gateway.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [aws_lambda_function.plaid.arn] }]
  })
}
