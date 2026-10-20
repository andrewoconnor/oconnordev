locals {
  schwab_proxy_function_name = "hermes-schwab-proxy"
}

data "archive_file" "schwab_proxy" {
  type        = "zip"
  source_dir  = "${local.repo_root}/infra/aws/tools/lambdas/schwab_proxy"
  output_path = "${path.module}/.terraform-archives/schwab_proxy.zip"
  excludes    = ["test_*.py", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "schwab_proxy" {
  # checkov:skip=CKV_AWS_158:Encrypted with the default AWS-owned key; the function logs no request data.
  # checkov:skip=CKV_AWS_338:Fourteen-day retention bounds a diagnostic log, not an audit trail.
  name              = "/aws/lambda/${local.schwab_proxy_function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "schwab_proxy" {
  name = "hermes-schwab-proxy"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "schwab_proxy" {
  name = "write-own-logs"
  role = aws_iam_role.schwab_proxy.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.schwab_proxy.arn}:*"] }]
  })
}

resource "aws_lambda_function" "schwab_proxy" {
  # checkov:skip=CKV_AWS_116:Synchronous Function URL invocations only; there is no asynchronous event to retry.
  # checkov:skip=CKV_AWS_117:The function calls Schwab's public API; a VPC would need NAT egress for no benefit.
  # checkov:skip=CKV_AWS_173:No environment variables.
  # checkov:skip=CKV_AWS_272:Code signing is not configured for this account; archive_file builds the package and source_code_hash tracks it.
  # checkov:skip=CKV_AWS_50:A single synchronous forward per call; tracing adds no diagnostic value.
  function_name                  = local.schwab_proxy_function_name
  role                           = aws_iam_role.schwab_proxy.arn
  handler                        = "schwab_proxy.handler"
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  timeout                        = 25
  memory_size                    = 128
  reserved_concurrent_executions = 2
  filename                       = data.archive_file.schwab_proxy.output_path
  source_code_hash               = data.archive_file.schwab_proxy.output_base64sha256

  depends_on = [aws_cloudwatch_log_group.schwab_proxy, aws_iam_role_policy.schwab_proxy]
}

resource "aws_lambda_function_url" "schwab_proxy" {
  # checkov:skip=CKV_AWS_258:The Authorization header carries the caller's Schwab bearer token, so it cannot carry SigV4. The function forwards only that caller's token to read-only Schwab GET paths.
  function_name      = aws_lambda_function.schwab_proxy.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "schwab_proxy_url" {
  # checkov:skip=CKV_AWS_301:The gateway reaches this URL with a Schwab bearer token, not AWS credentials. The function forwards only that token to read-only Schwab GET paths.
  statement_id           = "PublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.schwab_proxy.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "schwab_proxy_invoke" {
  # checkov:skip=CKV_AWS_301:The gateway reaches this URL with a Schwab bearer token, not AWS credentials. The function forwards only that token to read-only Schwab GET paths.
  statement_id             = "InvokeThroughFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.schwab_proxy.function_name
  principal                = "*"
  invoked_via_function_url = true
}
