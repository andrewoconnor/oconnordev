variable "microsoft365_runtime_enabled" {
  description = "Owner-only activation after image publication and independent delegated consumer cache bootstrap. No target or Lambda is deployed by default."
  type        = bool
  default     = false
}

variable "microsoft365_image_digest" {
  description = "Actual owner-published single linux/arm64 ECR manifest digest; tags and invented placeholder digests are not rollout inputs."
  type        = string
  default     = ""
  validation {
    condition     = var.microsoft365_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.microsoft365_image_digest))
    error_message = "Use an immutable sha256 manifest digest, not an image tag or URI."
  }
}

variable "microsoft365_client_id" {
  description = "Nonsecret application UUID for the owner's separately approved consumer delegated consent. No client secret or token."
  type        = string
  default     = ""
  validation {
    condition     = var.microsoft365_client_id == "" || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.microsoft365_client_id))
    error_message = "Use the approved application client UUID, never a credential."
  }
}

variable "microsoft365_owner_home_account_id" {
  description = "Immutable nonsecret consumer MSAL homeAccountId selected and verified by the owner during independent onboarding. Never inferred from the first cached identity."
  type        = string
  default     = ""
  validation {
    condition     = var.microsoft365_owner_home_account_id == "" || can(regex("^[A-Za-z0-9_-]{1,128}\\.9188040d-6c67-4c5b-b112-36a304b66dad$", var.microsoft365_owner_home_account_id))
    error_message = "Use the exact nonsecret MSAL homeAccountId (uid.utid), not email or a token."
  }
}

locals {
  microsoft365_function_name = "hermes-microsoft365-mcp"
  microsoft365_function_arn  = "arn:${data.aws_partition.current.partition}:lambda:us-east-1:${data.aws_caller_identity.current.account_id}:function:${local.microsoft365_function_name}"
}

# Bootstrap resources intentionally exist while runtime activation is false.
resource "aws_ecr_repository" "microsoft365" {
  # checkov:skip=CKV_AWS_136:AWS-managed ECR encryption avoids a new paid customer-managed KMS key for this low-duty personal workload.
  name                 = "hermes-microsoft365-mcp"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  encryption_configuration { encryption_type = "AES256" }
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository_policy" "microsoft365_lambda_pull" {
  repository = aws_ecr_repository.microsoft365.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "OnlyThisLambdaMayRetrieveImage"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
      Condition = { ArnLike = { "aws:SourceArn" = local.microsoft365_function_arn } }
    }]
  })
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
  count             = var.microsoft365_runtime_enabled ? 1 : 0
  name              = "/aws/lambda/${local.microsoft365_function_name}"
  retention_in_days = 14
}

data "aws_iam_policy_document" "microsoft365_runtime" {
  count = var.microsoft365_runtime_enabled ? 1 : 0
  statement {
    sid       = "OnlyTheConsumerCache"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
    resources = [aws_secretsmanager_secret.microsoft365_cache.arn]
  }
  statement {
    sid       = "OnlyThisFunctionLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.microsoft365[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "microsoft365_runtime" {
  count  = var.microsoft365_runtime_enabled ? 1 : 0
  name   = "single-consumer-cache-and-logs"
  role   = aws_iam_role.microsoft365_runtime.id
  policy = data.aws_iam_policy_document.microsoft365_runtime[0].json
}

resource "aws_lambda_function" "microsoft365" {
  # checkov:skip=CKV_AWS_117:No VPC/NAT; public Microsoft HTTPS APIs only, bounded by the runtime.
  # checkov:skip=CKV_AWS_116:Synchronous read-only MCP; no asynchronous retries or DLQ storing private mail payloads.
  # checkov:skip=CKV_AWS_173:Only nonsecret pins and a fixed secret ARN in environment; AWS-managed encryption.
  # checkov:skip=CKV_AWS_272:No code signing config for image-based Lambda; immutable ECR digest is owner-reviewed.
  # checkov:skip=CKV_AWS_50:Disable X-Ray to avoid recording consumer mail request details.
  count                          = var.microsoft365_runtime_enabled ? 1 : 0
  function_name                  = local.microsoft365_function_name
  role                           = aws_iam_role.microsoft365_runtime.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.microsoft365.repository_url}@${var.microsoft365_image_digest}"
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
      EXPECTED_HOME_ACCOUNT_ID                     = var.microsoft365_owner_home_account_id
      M365_CLIENT_ID                               = var.microsoft365_client_id
      AWS_LWA_INVOKE_MODE                          = "buffered"
      AWS_LWA_READINESS_CHECK_PATH                 = "/health"
      AWS_LWA_READINESS_CHECK_MIN_UNHEALTHY_STATUS = "201"
      AWS_LWA_PORT                                 = "8080"
    }
  }
  lifecycle {
    precondition {
      condition     = var.microsoft365_image_digest != "" && var.microsoft365_owner_home_account_id != "" && var.microsoft365_client_id != ""
      error_message = "Activation requires an actual owner-published digest and verified consumer homeAccountId; bootstrap resources can be applied with runtime disabled."
    }
    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "This single-region runtime must be provisioned in us-east-1."
    }
  }
  depends_on = [aws_iam_role_policy.microsoft365_runtime, aws_ecr_repository_policy.microsoft365_lambda_pull]
}

resource "aws_lambda_function_url" "microsoft365" {
  count              = var.microsoft365_runtime_enabled ? 1 : 0
  function_name      = aws_lambda_function.microsoft365[0].function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "BUFFERED"
}

# Same-account identity grants suffice. No public resource permission, and no
# misleading claim that these allows exclude other identity-authorized roles.
data "aws_iam_policy_document" "microsoft365_gateway_invoke" {
  count = var.microsoft365_runtime_enabled ? 1 : 0
  statement {
    actions   = ["lambda:InvokeFunctionUrl"]
    resources = [aws_lambda_function.microsoft365[0].arn]
    condition {
      test     = "StringEquals"
      variable = "lambda:FunctionUrlAuthType"
      values   = ["AWS_IAM"]
    }
  }
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.microsoft365[0].arn]
    condition {
      test     = "Bool"
      variable = "lambda:InvokedViaFunctionUrl"
      values   = ["true"]
    }
  }
}

resource "aws_iam_role_policy" "microsoft365_gateway_invoke" {
  count  = var.microsoft365_runtime_enabled ? 1 : 0
  name   = "microsoft365-function-url-only"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.microsoft365_gateway_invoke[0].json
}

output "microsoft365_bootstrap" {
  description = "Nonsecret owner bootstrap references; no cache values."
  value = {
    repository_url     = aws_ecr_repository.microsoft365.repository_url
    publisher_role_arn = aws_iam_role.microsoft365_image_publisher.arn
    cache_secret_arn   = aws_secretsmanager_secret.microsoft365_cache.arn
  }
}
