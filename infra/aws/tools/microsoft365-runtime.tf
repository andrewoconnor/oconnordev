locals {
  microsoft365_image_digest          = "sha256:46b45e6a4f9ef010144cc3f16bc7ad58e99a5a4d1ab157a8c0c5b130f076aac0"
  microsoft365_client_id             = "084a3e9f-a9f4-43f7-89f9-d229cf97853e"
  microsoft365_owner_home_account_id = "00000000-0000-0000-592d-43aab53672fd.9188040d-6c67-4c5b-b112-36a304b66dad"
  microsoft365_function_name         = "hermes-microsoft365-mcp"
  microsoft365_function_arn          = "arn:${data.aws_partition.current.partition}:lambda:us-east-1:${data.aws_caller_identity.current.account_id}:function:${local.microsoft365_function_name}"
}

# Metadata only. No value, cache migration, token, consent or secret-version in IaC.
resource "aws_secretsmanager_secret" "microsoft365_cache" {
  # checkov:skip=CKV_AWS_149:AWS-managed Secrets Manager key; runtime alone reads/writes the one cache ARN.
  # checkov:skip=CKV2_AWS_57:MSAL refresh-token rotation is performed by the serialized runtime, not a competing Secrets Manager rotation function.
  name                    = "/hermes/microsoft365/msal-cache"
  description             = "Owner-bootstrapped delegated consumer MSAL cache; only the serialized Microsoft365 runtime may refresh it."
  recovery_window_in_days = 30
}

resource "aws_iam_role" "microsoft365_runtime" {
  name = "hermes-microsoft365-runtime"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_cloudwatch_log_group" "microsoft365" {
  # checkov:skip=CKV_AWS_158:AWS-managed log encryption; no new paid customer-managed key.
  # checkov:skip=CKV_AWS_338:14-day finite retention deliberately minimizes personal-mail metadata retention and idle cost.
  name              = "/aws/lambda/${local.microsoft365_function_name}"
  retention_in_days = 14
}

data "aws_iam_policy_document" "microsoft365_runtime" {
  statement {
    sid       = "OnlyTheConsumerCache"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
    resources = [aws_secretsmanager_secret.microsoft365_cache.arn]
  }
  statement {
    sid       = "OnlyThisFunctionLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.microsoft365.arn}:*"]
  }
}

resource "aws_iam_role_policy" "microsoft365_runtime" {
  name   = "single-consumer-cache-and-logs"
  role   = aws_iam_role.microsoft365_runtime.id
  policy = data.aws_iam_policy_document.microsoft365_runtime.json
}

resource "aws_lambda_function" "microsoft365" {
  # checkov:skip=CKV_AWS_117:No VPC/NAT; public Microsoft HTTPS APIs only, bounded by the runtime.
  # checkov:skip=CKV_AWS_116:Synchronous read-only MCP; no asynchronous retries or DLQ storing private mail payloads.
  # checkov:skip=CKV_AWS_173:Only nonsecret pins and a fixed secret ARN in environment; AWS-managed encryption.
  # checkov:skip=CKV_AWS_272:No code signing config for image-based Lambda; immutable ECR digest is owner-reviewed.
  # checkov:skip=CKV_AWS_50:Disable X-Ray to avoid recording consumer mail request details.
  function_name                  = local.microsoft365_function_name
  role                           = aws_iam_role.microsoft365_runtime.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.tools_images.repository_url}@${local.microsoft365_image_digest}"
  architectures                  = ["arm64"]
  memory_size                    = 512
  timeout                        = 25
  reserved_concurrent_executions = 1
  publish                        = false
  ephemeral_storage { size = 512 }
  tracing_config { mode = "PassThrough" }
  environment {
    variables = {
      SECRET_ARN                                   = aws_secretsmanager_secret.microsoft365_cache.arn
      EXPECTED_HOME_ACCOUNT_ID                     = local.microsoft365_owner_home_account_id
      M365_CLIENT_ID                               = local.microsoft365_client_id
      AWS_LWA_INVOKE_MODE                          = "buffered"
      AWS_LWA_READINESS_CHECK_PATH                 = "/health"
      AWS_LWA_READINESS_CHECK_MIN_UNHEALTHY_STATUS = "201"
      AWS_LWA_PORT                                 = "8080"
    }
  }
  lifecycle {
    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "This single-region runtime must be provisioned in us-east-1."
    }
  }
  depends_on = [aws_iam_role_policy.microsoft365_runtime, aws_ecr_repository_policy.tools_images]
}

resource "aws_lambda_function_url" "microsoft365" {
  function_name      = aws_lambda_function.microsoft365.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "BUFFERED"
}

# Same-account identity grants suffice. No public resource permission, and no
# misleading claim that these allows exclude other identity-authorized roles.
data "aws_iam_policy_document" "microsoft365_gateway_invoke" {
  statement {
    actions   = ["lambda:InvokeFunctionUrl"]
    resources = [aws_lambda_function.microsoft365.arn]
    condition {
      test     = "StringEquals"
      variable = "lambda:FunctionUrlAuthType"
      values   = ["AWS_IAM"]
    }
  }
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.microsoft365.arn]
    condition {
      test     = "Bool"
      variable = "lambda:InvokedViaFunctionUrl"
      values   = ["true"]
    }
  }
}

resource "aws_iam_role_policy" "microsoft365_gateway_invoke" {
  name   = "microsoft365-function-url-only"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.microsoft365_gateway_invoke.json
}

output "microsoft365_bootstrap" {
  description = "Nonsecret owner bootstrap references; no cache values."
  value = {
    repository_url     = aws_ecr_repository.tools_images.repository_url
    publisher_role_arn = aws_iam_role.tools_image_publisher.arn
    cache_secret_arn   = aws_secretsmanager_secret.microsoft365_cache.arn
  }
}
