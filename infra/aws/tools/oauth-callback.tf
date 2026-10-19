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
    sid       = "ReadAdapterClientSecret"
    effect    = "Allow"
    actions   = ["cognito-idp:DescribeUserPoolClient"]
    resources = [aws_cognito_user_pool.hermes.arn]
  }

  statement {
    sid     = "CompleteGatewayConsent"
    effect  = "Allow"
    actions = ["bedrock-agentcore:CompleteResourceTokenAuth"]
    resources = [
      aws_bedrockagentcore_oauth2_credential_provider.schwab.credential_provider_arn,
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:token-vault/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.oauth_callback.arn}:*"]
  }
}

resource "aws_iam_role_policy" "oauth_callback" {
  name   = "complete-gateway-consent"
  role   = aws_iam_role.oauth_callback.id
  policy = data.aws_iam_policy_document.oauth_callback.json
}

resource "aws_lambda_function" "oauth_callback" {
  # checkov:skip=CKV_AWS_116:Synchronous Function URL invocations only; there is no asynchronous event to retry.
  # checkov:skip=CKV_AWS_117:The function calls public Cognito and AgentCore endpoints; a VPC would need NAT egress for no benefit.
  # checkov:skip=CKV_AWS_173:Environment variables hold only the user pool ID, client ID, token URL and scope, not secrets.
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
      USER_POOL_ID = aws_cognito_user_pool.hermes.id
      CLIENT_ID    = aws_cognito_user_pool_client.hermes.id
      TOKEN_URL    = local.cognito_token_url
      SCOPE        = aws_cognito_resource_server.hermes.scope_identifiers[0]
    }
  }

  depends_on = [aws_cloudwatch_log_group.oauth_callback, aws_iam_role_policy.oauth_callback]
}

resource "aws_lambda_function_url" "oauth_callback" {
  # checkov:skip=CKV_AWS_258:A browser redirect cannot carry AWS credentials. The function only completes consent sessions that the adapter's own Cognito identity started.
  function_name      = aws_lambda_function.oauth_callback.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "oauth_callback_url" {
  # checkov:skip=CKV_AWS_301:The browser redirect from AgentCore is anonymous. The function only completes consent sessions that the adapter's own Cognito identity started.
  statement_id           = "PublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.oauth_callback.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "oauth_callback_invoke" {
  # checkov:skip=CKV_AWS_301:The browser redirect from AgentCore is anonymous. The function only completes consent sessions that the adapter's own Cognito identity started.
  statement_id             = "InvokeThroughFunctionUrl"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.oauth_callback.function_name
  principal                = "*"
  invoked_via_function_url = true
}

output "oauth_callback_return_url" {
  description = "Hosted AgentCore 3LO return URL that completes consent without a local script."
  value       = local.oauth_callback_return_url
}
