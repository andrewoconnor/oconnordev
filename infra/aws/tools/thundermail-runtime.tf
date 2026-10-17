# Dormant direct native Lambda; no HTTP listener, Function URL, Node or LWA.
variable "thundermail_runtime_enabled" {
  description = "Requested runtime flag; activation is source-blocked regardless of input until a separate reviewed source change."
  type        = bool
  default     = false
}
variable "thundermail_secret_bootstrap_enabled" {
  description = "Explicit paid Secrets Manager metadata opt-in; creates no value. Independent of runtime activation."
  type        = bool
  default     = false
}
variable "thundermail_secret_arn" {
  description = "Existing exact same-account us-east-1 app-password secret ARN; leave empty when creating new metadata. Never the value."
  type        = string
  default     = ""
  validation {
    condition     = var.thundermail_secret_arn == "" || can(regex("^arn:aws:secretsmanager:us-east-1:[0-9]{12}:secret:/hermes/thundermail/app-password-[A-Za-z0-9]{6}$", var.thundermail_secret_arn))
    error_message = "Use an exact us-east-1 Secrets Manager ARN, no wildcard, version, or account alias."
  }
}
variable "thundermail_image_digest" {
  description = "Reviewed tested single linux/arm64 ECR manifest digest, not config/archive hash or tag."
  type        = string
  default     = ""
  validation {
    condition     = var.thundermail_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.thundermail_image_digest))
    error_message = "Use an immutable sha256 manifest digest."
  }
}
locals {
  # Source-locked: advisory, ARM64/provider, policy and redistribution review
  # unresolved. No Terraform input can approve a digest or bypass readiness.
  # Opening activation requires a separate reviewed source change.
  thundermail_activation_ready = false
  thundermail_function_name    = "hermes-thundermail-mcp"
  thundermail_function_arn     = "arn:${data.aws_partition.current.partition}:lambda:us-east-1:${data.aws_caller_identity.current.account_id}:function:${local.thundermail_function_name}"
  thundermail_secret_arn       = var.thundermail_secret_bootstrap_enabled ? aws_secretsmanager_secret.thundermail[0].arn : var.thundermail_secret_arn
}
resource "aws_secretsmanager_secret" "thundermail" {
  # checkov:skip=CKV_AWS_149:AWS-managed key; no extra paid CMK.
  # checkov:skip=CKV2_AWS_57:Owner rotates the app password out of band; runtime has no write permission.
  count                   = var.thundermail_secret_bootstrap_enabled ? 1 : 0
  name                    = "/hermes/thundermail/app-password"
  description             = "Single owner Thundermail app password; owner provisions value outside IaC."
  recovery_window_in_days = 30
}
resource "aws_iam_role" "thundermail" {
  count = var.thundermail_runtime_enabled ? 1 : 0
  name  = "hermes-thundermail-runtime"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}
resource "aws_cloudwatch_log_group" "thundermail" {
  # checkov:skip=CKV_AWS_158:AWS-managed encryption, no extra CMK.
  # checkov:skip=CKV_AWS_338:Finite 14-day retention minimizes private metadata and storage.
  count             = var.thundermail_runtime_enabled ? 1 : 0
  name              = "/aws/lambda/${local.thundermail_function_name}"
  retention_in_days = 14
}
resource "aws_iam_role_policy" "thundermail_runtime" {
  count = var.thundermail_runtime_enabled ? 1 : 0
  name  = "one-app-password-read-and-own-logs"
  role  = aws_iam_role.thundermail[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [local.thundermail_secret_arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.thundermail[0].arn}:*"] }
    ]
  })
}
resource "aws_lambda_function" "thundermail" {
  # checkov:skip=CKV_AWS_117:No VPC/NAT; public IMAPS with pinned endpoint and certificate verification.
  # checkov:skip=CKV_AWS_116:Synchronous reads; no asynchronous mail payload DLQ.
  # checkov:skip=CKV_AWS_173:Only a nonsecret ARN in environment, AWS-managed encryption.
  # checkov:skip=CKV_AWS_272:Container image pinned by reviewed immutable manifest digest.
  # checkov:skip=CKV_AWS_50:No X-Ray mail metadata.
  count                          = var.thundermail_runtime_enabled ? 1 : 0
  function_name                  = local.thundermail_function_name
  role                           = aws_iam_role.thundermail[0].arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.tools_images.repository_url}@${var.thundermail_image_digest}"
  architectures                  = ["arm64"]
  memory_size                    = 128
  timeout                        = 10
  reserved_concurrent_executions = 1
  publish                        = false
  ephemeral_storage { size = 512 }
  tracing_config { mode = "PassThrough" }
  environment { variables = { THUNDERMAIL_CREDENTIAL_SECRET_ARN = local.thundermail_secret_arn } }
  lifecycle {
    precondition {
      condition     = local.thundermail_activation_ready
      error_message = "Activation is source-blocked: GHSA-8ffr-xgwf-xj56 and independent artifact/provider/policy/redistribution review unresolved. A reviewed source change is required; no input digest is approved."
    }
    precondition {
      condition     = var.thundermail_image_digest != "" && (var.thundermail_secret_bootstrap_enabled != (var.thundermail_secret_arn != ""))
      error_message = "Activation needs a tested digest and exactly one managed-metadata or existing-ARN secret source."
    }
    precondition {
      condition     = var.thundermail_secret_bootstrap_enabled || startswith(var.thundermail_secret_arn, "arn:aws:secretsmanager:us-east-1:${data.aws_caller_identity.current.account_id}:secret:")
      error_message = "Existing secret must be in this account and us-east-1."
    }
    precondition {
      condition     = data.aws_region.current.region == "us-east-1" && data.aws_partition.current.partition == "aws"
      error_message = "Only the existing commercial AWS us-east-1 tools account is supported."
    }
  }
  depends_on = [aws_iam_role_policy.thundermail_runtime, aws_ecr_repository_policy.microsoft365_lambda_pull]
}
resource "aws_iam_role_policy" "thundermail_gateway_invoke" {
  count = var.thundermail_runtime_enabled ? 1 : 0
  name  = "thundermail-native-invoke-only"
  role  = aws_iam_role.hermes_gateway.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [local.thundermail_function_arn] }]
  })
}
output "thundermail_bootstrap" {
  description = "Nonsecret references only; default does not create paid secret metadata."
  value = {
    secret_arn     = local.thundermail_secret_arn
    repository_url = aws_ecr_repository.tools_images.repository_url
  }
}
