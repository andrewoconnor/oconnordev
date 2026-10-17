# Direct native Lambda; no HTTP listener, Function URL, Node or LWA.
locals {
  thundermail_image_digest  = "sha256:8cc615bc327762c8b4bf371b770632fc29028326665b4eab8abb1693edfd5e4c"
  thundermail_function_name = "hermes-thundermail-mcp"
  thundermail_function_arn  = "arn:${data.aws_partition.current.partition}:lambda:us-east-1:${data.aws_caller_identity.current.account_id}:function:${local.thundermail_function_name}"
}
resource "aws_secretsmanager_secret" "thundermail" {
  # checkov:skip=CKV_AWS_149:AWS-managed key; no extra paid CMK.
  # checkov:skip=CKV2_AWS_57:Owner rotates the app password out of band; runtime has no write permission.
  name                    = "/hermes/thundermail/app-password"
  description             = "Single owner Thundermail app password; owner provisions value outside IaC."
  recovery_window_in_days = 30
}
resource "aws_iam_role" "thundermail" {
  name = "hermes-thundermail-runtime"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}
resource "aws_cloudwatch_log_group" "thundermail" {
  # checkov:skip=CKV_AWS_158:AWS-managed encryption, no extra CMK.
  # checkov:skip=CKV_AWS_338:Finite 14-day retention minimizes private metadata and storage.
  name              = "/aws/lambda/${local.thundermail_function_name}"
  retention_in_days = 14
}
resource "aws_iam_role_policy" "thundermail_runtime" {
  name = "one-app-password-read-and-own-logs"
  role = aws_iam_role.thundermail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.thundermail.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.thundermail.arn}:*"] }
    ]
  })
}
resource "aws_lambda_function" "thundermail" {
  # checkov:skip=CKV_AWS_117:No VPC/NAT; public IMAPS with pinned endpoint and certificate verification.
  # checkov:skip=CKV_AWS_116:Synchronous reads; no asynchronous mail payload DLQ.
  # checkov:skip=CKV_AWS_173:Only a nonsecret ARN in environment, AWS-managed encryption.
  # checkov:skip=CKV_AWS_272:Container image pinned by reviewed immutable manifest digest.
  # checkov:skip=CKV_AWS_50:No X-Ray mail metadata.
  function_name                  = local.thundermail_function_name
  role                           = aws_iam_role.thundermail.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.tools_images.repository_url}@${local.thundermail_image_digest}"
  architectures                  = ["arm64"]
  memory_size                    = 128
  timeout                        = 10
  reserved_concurrent_executions = 1
  publish                        = false
  ephemeral_storage { size = 512 }
  tracing_config { mode = "PassThrough" }
  environment { variables = { THUNDERMAIL_CREDENTIAL_SECRET_ARN = aws_secretsmanager_secret.thundermail.arn } }
  lifecycle {
    precondition {
      condition     = data.aws_region.current.region == "us-east-1" && data.aws_partition.current.partition == "aws"
      error_message = "Only the existing commercial AWS us-east-1 tools account is supported."
    }
  }
  depends_on = [aws_iam_role_policy.thundermail_runtime, aws_ecr_repository_policy.tools_images]
}
resource "aws_iam_role_policy" "thundermail_gateway_invoke" {
  name = "thundermail-native-invoke-only"
  role = aws_iam_role.hermes_gateway.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [local.thundermail_function_arn] }]
  })
}
output "thundermail_bootstrap" {
  description = "Nonsecret references only."
  value = {
    secret_arn     = aws_secretsmanager_secret.thundermail.arn
    repository_url = aws_ecr_repository.tools_images.repository_url
  }
}
