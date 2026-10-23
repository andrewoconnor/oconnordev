locals {
  oauth_callback_function_name = "hermes-oauth-callback"
  oauth_callback_return_url    = "${aws_lambda_function_url.oauth_callback.function_url}callback"
}

data "archive_file" "oauth_callback" {
  type        = "zip"
  source_dir  = "${local.repo_root}/infra/aws/tools/lambdas/oauth_callback"
  output_path = "${path.module}/.terraform-archives/oauth_callback.zip"
  excludes    = ["test_*.py", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "oauth_callback" {
  # checkov:skip=CKV_AWS_158:Encrypted with the default AWS-owned key; the records hold only request metadata, never tokens.
  # checkov:skip=CKV_AWS_338:Fourteen-day retention bounds a diagnostic log, not an audit trail.
  name              = "/aws/lambda/${local.oauth_callback_function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "oauth_callback" {
  name = "hermes-oauth-callback"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

data "aws_iam_policy_document" "oauth_callback" {
  statement {
    sid       = "CompleteSchwabConsent"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:CompleteResourceTokenAuth"]
    resources = local.schwab_identity_scope
  }

  statement {
    sid       = "ReadSchwabOauthClientSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = local.schwab_secret_arns
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.oauth_callback.arn}:*"]
  }
}

resource "aws_iam_role_policy" "oauth_callback" {
  name   = "complete-schwab-consent"
  role   = aws_iam_role.oauth_callback.id
  policy = data.aws_iam_policy_document.oauth_callback.json
}

resource "aws_lambda_function" "oauth_callback" {
  # checkov:skip=CKV_AWS_116:Synchronous Function URL invocations only; there is no asynchronous event to retry.
  # checkov:skip=CKV_AWS_117:The function calls the public AgentCore endpoint; a VPC would need NAT egress for no benefit.
  # checkov:skip=CKV_AWS_173:The only environment variable is the Schwab owner user ID, not a secret.
  # checkov:skip=CKV_AWS_272:Code signing is not configured for this account; archive_file builds the package and source_code_hash tracks it.
  # checkov:skip=CKV_AWS_50:A single synchronous call per consent; tracing adds no diagnostic value.
  function_name                  = local.oauth_callback_function_name
  role                           = aws_iam_role.oauth_callback.arn
  handler                        = "oauth_callback.handler"
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  timeout                        = 15
  memory_size                    = 128
  reserved_concurrent_executions = 1
  filename                       = data.archive_file.oauth_callback.output_path
  source_code_hash               = data.archive_file.oauth_callback.output_base64sha256

  environment {
    variables = {
      USER_ID = local.schwab_user_id
    }
  }

  depends_on = [aws_cloudwatch_log_group.oauth_callback, aws_iam_role_policy.oauth_callback]
}

resource "aws_lambda_function_url" "oauth_callback" {
  # checkov:skip=CKV_AWS_258:A browser redirect cannot carry AWS credentials. The function only binds AgentCore consent sessions to the Schwab owner user ID.
  function_name      = aws_lambda_function.oauth_callback.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "oauth_callback_url" {
  # checkov:skip=CKV_AWS_301:The browser redirect from AgentCore is anonymous. The function only binds AgentCore consent sessions to the Schwab owner user ID.
  statement_id           = "PublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.oauth_callback.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "oauth_callback_invoke" {
  # checkov:skip=CKV_AWS_301:The browser redirect from AgentCore is anonymous. The function only binds AgentCore consent sessions to the Schwab owner user ID.
  statement_id             = "InvokeThroughFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.oauth_callback.function_name
  principal                = "*"
  invoked_via_function_url = true
}

output "oauth_callback_return_url" {
  description = "Hosted AgentCore 3LO return URL that completes Schwab consent."
  value       = local.oauth_callback_return_url
}
