variable "hermes_alarm_webhook_url" {
  description = "Hermes Cloud webhook route that receives CloudWatch alarm state changes. The route must use the generic HMAC signature scheme."
  type        = string
  default     = "https://supervenient-aerodrome-1746.agents.nousresearch.com/webhooks/aws-alarms"

  validation {
    condition     = can(regex("^https://[a-z0-9-]+\\.agents\\.nousresearch\\.com/webhooks/[a-z0-9-]+$", var.hermes_alarm_webhook_url))
    error_message = "Set an https Hermes Cloud webhook route URL of the form https://<agent>.agents.nousresearch.com/webhooks/<route>."
  }
}

locals {
  alarm_webhook_function_name  = "hermes-alarm-webhook"
  alarm_webhook_default_bus    = "arn:aws:events:us-east-1:${local.accounts["TOOLS"]}:event-bus/default"
  alarm_webhook_source_account = local.accounts["PRODUCTION"]
}

resource "aws_ssm_parameter" "alarm_webhook_hmac" {
  # checkov:skip=CKV_AWS_337:The AWS-managed aws/ssm key encrypts this SecureString at no cost; a customer-managed key would add $1 a month.
  name             = "/hermes/webhooks/aws-alarms-hmac"
  description      = "HMAC secret shared with the Hermes aws-alarms webhook route; the owner provisions the value outside OpenTofu."
  type             = "SecureString"
  value_wo         = "unset"
  value_wo_version = 1
}

data "archive_file" "alarm_webhook" {
  type        = "zip"
  source_dir  = "${local.repo_root}/infra/aws/tools/lambdas/alarm_webhook"
  output_path = "${path.module}/.terraform-archives/alarm_webhook.zip"
  excludes    = ["test_*.py", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "alarm_webhook" {
  # checkov:skip=CKV_AWS_158:Encrypted with the default AWS-owned key; the function logs only errors, never the HMAC secret.
  # checkov:skip=CKV_AWS_338:Fourteen-day retention bounds operational logs, not an audit trail.
  name              = "/aws/lambda/${local.alarm_webhook_function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "alarm_webhook" {
  name = local.alarm_webhook_function_name
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "alarm_webhook" {
  name = "hmac-secret-read-and-own-logs"
  role = aws_iam_role.alarm_webhook.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = [aws_ssm_parameter.alarm_webhook_hmac.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.alarm_webhook.arn}:*"] }
    ]
  })
}

resource "aws_lambda_function" "alarm_webhook" {
  # checkov:skip=CKV_AWS_116:Undelivered alarms are not queued. The alerts topic in each account still emails every alarm.
  # checkov:skip=CKV_AWS_117:The function must reach the public Hermes Cloud webhook; a VPC attachment would need NAT egress.
  # checkov:skip=CKV_AWS_173:The environment holds only the webhook URL and the SSM parameter name, never the HMAC secret.
  # checkov:skip=CKV_AWS_272:Repository archive and source_code_hash bind the Python ZIP; account code signing is not configured.
  # checkov:skip=CKV_AWS_50:The function makes one signed POST; tracing would add no useful diagnostics.
  function_name                  = local.alarm_webhook_function_name
  role                           = aws_iam_role.alarm_webhook.arn
  handler                        = "alarm_webhook.handler"
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  timeout                        = 15
  memory_size                    = 128
  reserved_concurrent_executions = 2
  filename                       = data.archive_file.alarm_webhook.output_path
  source_code_hash               = data.archive_file.alarm_webhook.output_base64sha256

  environment {
    variables = {
      WEBHOOK_URL           = var.hermes_alarm_webhook_url
      SECRET_PARAMETER_NAME = aws_ssm_parameter.alarm_webhook_hmac.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.alarm_webhook, aws_iam_role_policy.alarm_webhook]
}

resource "aws_lambda_function_event_invoke_config" "alarm_webhook" {
  function_name                = aws_lambda_function.alarm_webhook.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600
}

resource "aws_cloudwatch_event_bus_policy" "production_alarms" {
  event_bus_name = "default"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "ProductionAlarmStateChanges"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${local.alarm_webhook_source_account}:root" }
      Action    = "events:PutEvents"
      Resource  = local.alarm_webhook_default_bus
    }]
  })
}

resource "aws_cloudwatch_event_rule" "alarm_webhook" {
  name        = local.alarm_webhook_function_name
  description = "Sends ALARM and OK state changes from TOOLS and PRODUCTION alarms to the Hermes webhook."
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    account       = [local.accounts["TOOLS"], local.alarm_webhook_source_account]
    detail        = { state = { value = ["ALARM", "OK"] } }
  })
}

resource "aws_cloudwatch_event_target" "alarm_webhook" {
  rule = aws_cloudwatch_event_rule.alarm_webhook.name
  arn  = aws_lambda_function.alarm_webhook.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }
}

resource "aws_lambda_permission" "alarm_webhook" {
  statement_id  = "AllowExecutionFromEventBridgeAlarmWebhook"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alarm_webhook.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.alarm_webhook.arn
}
