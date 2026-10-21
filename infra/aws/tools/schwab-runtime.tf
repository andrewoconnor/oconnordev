locals {
  schwab_function_name      = "hermes-schwab"
  schwab_user_id            = "owner"
  schwab_tool_schemas       = jsondecode(file("${path.module}/lambdas/schwab/tools.json")).tools
  schwab_identity_directory = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default"
  schwab_token_vault        = "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:token-vault/default"
  schwab_identity_scope     = [aws_bedrockagentcore_oauth2_credential_provider.schwab.credential_provider_arn, local.schwab_token_vault, local.schwab_identity_directory, local.schwab_workload_arn]
  schwab_workload_arn       = "${local.schwab_identity_directory}/workload-identity/${local.schwab_function_name}"
}

resource "aws_bedrockagentcore_workload_identity" "schwab" {
  name                                = local.schwab_function_name
  allowed_resource_oauth2_return_urls = [local.oauth_callback_return_url]
}

data "archive_file" "schwab" {
  type        = "zip"
  source_dir  = "${local.repo_root}/infra/aws/tools/lambdas/schwab"
  output_path = "${path.module}/.terraform-archives/schwab.zip"
  excludes    = ["test_*.py", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "schwab" {
  # checkov:skip=CKV_AWS_158:Encrypted with the default AWS-owned key; the function logs only AgentCore error names and messages, never tokens.
  # checkov:skip=CKV_AWS_338:Fourteen-day retention bounds a diagnostic log, not an audit trail.
  name              = "/aws/lambda/${local.schwab_function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "schwab" {
  name = "hermes-schwab"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

data "aws_iam_policy_document" "schwab" {
  statement {
    sid       = "OwnerWorkloadToken"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:GetWorkloadAccessTokenForUserId"]
    resources = [local.schwab_identity_directory, local.schwab_workload_arn]
  }

  statement {
    sid       = "SchwabTokenFromAgentCoreIdentity"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:GetResourceOauth2Token"]
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
    resources = ["${aws_cloudwatch_log_group.schwab.arn}:*"]
  }
}

resource "aws_iam_role_policy" "schwab" {
  name   = "owner-schwab-token-and-own-logs"
  role   = aws_iam_role.schwab.id
  policy = data.aws_iam_policy_document.schwab.json
}

resource "aws_lambda_function" "schwab" {
  # checkov:skip=CKV_AWS_116:Synchronous gateway invocations only; there is no asynchronous event to retry.
  # checkov:skip=CKV_AWS_117:The function calls public AgentCore and Schwab endpoints; a VPC would need NAT egress for no benefit.
  # checkov:skip=CKV_AWS_173:Environment variables hold only names, the user ID and the callback URL, not secrets.
  # checkov:skip=CKV_AWS_272:Code signing is not configured for this account; archive_file builds the package and source_code_hash tracks it.
  # checkov:skip=CKV_AWS_50:One token lookup and one GET per call; tracing adds no diagnostic value.
  function_name                  = local.schwab_function_name
  role                           = aws_iam_role.schwab.arn
  handler                        = "schwab.handler"
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  timeout                        = 25
  memory_size                    = 128
  reserved_concurrent_executions = 2
  filename                       = data.archive_file.schwab.output_path
  source_code_hash               = data.archive_file.schwab.output_base64sha256

  environment {
    variables = {
      WORKLOAD_NAME = aws_bedrockagentcore_workload_identity.schwab.name
      USER_ID       = local.schwab_user_id
      PROVIDER_NAME = aws_bedrockagentcore_oauth2_credential_provider.schwab.name
      RETURN_URL    = local.oauth_callback_return_url
    }
  }

  depends_on = [aws_cloudwatch_log_group.schwab, aws_iam_role_policy.schwab]
}

resource "aws_iam_role_policy" "schwab_gateway_invoke" {
  name = "schwab-native-invoke-only"
  role = aws_iam_role.hermes_gateway.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [aws_lambda_function.schwab.arn] }]
  })
}
