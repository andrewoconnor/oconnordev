variable "hermes_spacelift_rotation_interval_minutes" {
  description = "How often the Spacelift session token is re-minted. Spacelift reuses one fixed ten-hour expiry window per API key and re-minting does not extend it, so this cadence is what bounds the gap between that window rolling and a usable token being published. The alarm below evaluates over two intervals, so keep the interval well inside the ten-hour window."
  type        = number
  default     = 60

  validation {
    condition     = var.hermes_spacelift_rotation_interval_minutes >= 1 && var.hermes_spacelift_rotation_interval_minutes <= 720 && floor(var.hermes_spacelift_rotation_interval_minutes) == var.hermes_spacelift_rotation_interval_minutes
    error_message = "hermes_spacelift_rotation_interval_minutes must be a whole number of minutes between 1 and 720."
  }
}

variable "hermes_spacelift_token_remaining_floor_seconds" {
  description = "Alert when the published session token's remaining lifetime drops below this many seconds. A rotation that writes a nearly-expired token is a successful invocation and a failed rotation, so the alarm keys on the token's remaining life rather than on the function's exit status."
  type        = number
  default     = 7200

  validation {
    condition     = var.hermes_spacelift_token_remaining_floor_seconds >= 60 && var.hermes_spacelift_token_remaining_floor_seconds <= 32400
    error_message = "hermes_spacelift_token_remaining_floor_seconds must be between 60 and 32400 (nine hours), leaving headroom below the ten-hour window."
  }
}

variable "hermes_spacelift_rotation_log_retention_days" {
  description = "Retention in days for the rotation function's log group."
  type        = number
  default     = 14

  validation {
    condition = contains([
      1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180,
      365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653,
    ], var.hermes_spacelift_rotation_log_retention_days)
    error_message = "hermes_spacelift_rotation_log_retention_days must be one of the retention values CloudWatch Logs accepts."
  }
}

variable "hermes_spacelift_rotation_http_timeout_seconds" {
  description = "Connect and read timeout for the rotation function's calls to the Spacelift GraphQL and MCP endpoints."
  type        = number
  default     = 15

  validation {
    condition     = var.hermes_spacelift_rotation_http_timeout_seconds >= 1 && var.hermes_spacelift_rotation_http_timeout_seconds <= 60
    error_message = "hermes_spacelift_rotation_http_timeout_seconds must be between 1 and 60 seconds, and must stay below the function timeout."
  }
}

locals {
  spacelift_rotation_function_name    = "hermes-spacelift-session-token-rotation"
  spacelift_rotation_metric_namespace = "Hermes/SpaceliftAuth"
  spacelift_rotation_metric_remaining = "SessionTokenRemainingSeconds"
  spacelift_rotation_schedule         = "rate(${var.hermes_spacelift_rotation_interval_minutes} ${var.hermes_spacelift_rotation_interval_minutes == 1 ? "minute" : "minutes"})"
  spacelift_rotation_alarm_period     = var.hermes_spacelift_rotation_interval_minutes * 60
  spacelift_rotation_source_dir       = "${local.repo_root}/agents/hermes/rotation"
  spacelift_rotation_archive          = "${path.module}/.terraform-archives/spacelift_session_token.zip"
  spacelift_host                      = split("/", replace(var.hermes_spacelift_mcp_endpoint, "https://", ""))[0]
  spacelift_graphql_endpoint          = "https://${local.spacelift_host}/graphql"
}

data "archive_file" "spacelift_rotation" {
  type        = "zip"
  source_dir  = local.spacelift_rotation_source_dir
  output_path = local.spacelift_rotation_archive
}

resource "aws_cloudwatch_log_group" "spacelift_rotation" {
  # checkov:skip=CKV_AWS_158:Encrypted at rest with the default AWS-owned key. An AWS-managed key cannot be referenced here -- alias/aws/logs is created lazily by the service and does not resolve beforehand -- and a customer-managed key would need a key policy granting the log-delivery service kms:GenerateDataKey*, where a policy wrong in either direction fails the delivery silently rather than loudly.
  # checkov:skip=CKV_AWS_338:Retention is 14 days rather than a year. These records carry only token metadata -- iat, exp, remaining lifetime and whether the window rolled -- never the API key or the JWT, so the shorter retention bounds a diagnostic log rather than an audit trail.
  name              = "/aws/lambda/${local.spacelift_rotation_function_name}"
  retention_in_days = var.hermes_spacelift_rotation_log_retention_days
}

resource "aws_sqs_queue" "spacelift_rotation_delivery" {
  name                      = "hermes-spacelift-rotation-delivery-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "spacelift_rotation_failure" {
  name                      = "hermes-spacelift-rotation-failure-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

data "aws_iam_policy_document" "spacelift_rotation_delivery" {
  statement {
    sid     = "AllowEventBridgeScheduleDelivery"
    effect  = "Allow"
    actions = ["sqs:SendMessage"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    resources = [aws_sqs_queue.spacelift_rotation_delivery.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.spacelift_rotation.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "spacelift_rotation_delivery" {
  queue_url = aws_sqs_queue.spacelift_rotation_delivery.id
  policy    = data.aws_iam_policy_document.spacelift_rotation_delivery.json
}

data "aws_iam_policy_document" "spacelift_rotation_failure" {
  statement {
    sid     = "AllowLambdaAsyncFailureDestination"
    effect  = "Allow"
    actions = ["sqs:SendMessage"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    resources = [aws_sqs_queue.spacelift_rotation_failure.arn]

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_lambda_function.spacelift_rotation.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "spacelift_rotation_failure" {
  queue_url = aws_sqs_queue.spacelift_rotation_failure.id
  policy    = data.aws_iam_policy_document.spacelift_rotation_failure.json
}

data "aws_iam_policy_document" "spacelift_rotation_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "spacelift_rotation" {
  name               = "hermes-spacelift-session-token-rotation"
  assume_role_policy = data.aws_iam_policy_document.spacelift_rotation_trust.json
}

data "aws_iam_policy_document" "spacelift_rotation" {
  statement {
    sid       = "ReadLongLivedSpaceliftApiKey"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [data.aws_secretsmanager_secret.spacelift_api_key.arn]
  }

  statement {
    sid       = "WriteShortLivedSpaceliftSessionToken"
    effect    = "Allow"
    actions   = ["secretsmanager:PutSecretValue"]
    resources = [aws_secretsmanager_secret.spacelift_session_token.arn]
  }

  statement {
    sid       = "WriteRotationLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.spacelift_rotation.arn}:*"]
  }

  statement {
    sid       = "PublishRotationMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [local.spacelift_rotation_metric_namespace]
    }
  }

  statement {
    sid       = "SendAsyncFailuresToDeadLetterQueue"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.spacelift_rotation_failure.arn]
  }
}

resource "aws_iam_role_policy" "spacelift_rotation" {
  name   = "hermes-spacelift-session-token-rotation"
  role   = aws_iam_role.spacelift_rotation.id
  policy = data.aws_iam_policy_document.spacelift_rotation.json
}

resource "aws_lambda_function" "spacelift_rotation" {
  # checkov:skip=CKV_AWS_116:Async failures are routed to an on-failure destination by aws_lambda_function_event_invoke_config, which supersedes the deprecated dead_letter_config block.
  # checkov:skip=CKV_AWS_117:The function must reach Spacelift's public GraphQL and MCP endpoints; a VPC attachment would require NAT egress and add a failure mode with no security benefit, since the credential is held in Secrets Manager rather than reached over a private network.
  # checkov:skip=CKV_AWS_173:Every environment variable is a secret name, endpoint or timeout. The API key and the session JWT are never placed in the environment.
  # checkov:skip=CKV_AWS_272:Code signing is not configured for this account. The deployment package is built from the repository at plan time by archive_file and its hash is tracked in source_code_hash.
  # checkov:skip=CKV_AWS_50:Active tracing is not enabled. Rotation is a single synchronous call whose outcome is already alarmed on by remaining token lifetime and by the function's error metric, so distributed tracing adds no diagnostic value here.
  function_name                  = local.spacelift_rotation_function_name
  role                           = aws_iam_role.spacelift_rotation.arn
  handler                        = "spacelift_session_token.handler"
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  timeout                        = 30
  memory_size                    = 128
  reserved_concurrent_executions = 1
  filename                       = data.archive_file.spacelift_rotation.output_path
  source_code_hash               = data.archive_file.spacelift_rotation.output_base64sha256

  environment {
    variables = {
      API_KEY_SECRET_ID    = var.hermes_spacelift_api_key_secret_name
      TOKEN_SECRET_ID      = var.hermes_spacelift_session_token_secret_name
      TOKEN_JSON_KEY       = var.hermes_spacelift_session_token_json_key
      GRAPHQL_ENDPOINT     = local.spacelift_graphql_endpoint
      VERIFY_ENDPOINT      = var.hermes_spacelift_mcp_endpoint
      METRIC_NAMESPACE     = local.spacelift_rotation_metric_namespace
      METRIC_REMAINING     = local.spacelift_rotation_metric_remaining
      HTTP_TIMEOUT_SECONDS = tostring(var.hermes_spacelift_rotation_http_timeout_seconds)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.spacelift_rotation,
    aws_iam_role_policy.spacelift_rotation,
  ]
}

resource "aws_lambda_function_event_invoke_config" "spacelift_rotation" {
  function_name          = aws_lambda_function.spacelift_rotation.function_name
  maximum_retry_attempts = 2

  destination_config {
    on_failure {
      destination = aws_sqs_queue.spacelift_rotation_failure.arn
    }
  }
}

resource "aws_lambda_invocation" "spacelift_session_token_seed" {
  function_name = aws_lambda_function.spacelift_rotation.function_name
  input         = jsonencode({ source = "terraform-seed" })

  depends_on = [
    aws_lambda_function.spacelift_rotation,
    aws_iam_role_policy.spacelift_rotation,
    aws_lambda_function_event_invoke_config.spacelift_rotation,
  ]
}

resource "aws_cloudwatch_event_rule" "spacelift_rotation" {
  name                = "hermes-spacelift-session-token-rotation"
  description         = "Re-mints the Spacelift session token and republishes it for the AgentCore credential provider."
  schedule_expression = local.spacelift_rotation_schedule
}

resource "aws_cloudwatch_event_target" "spacelift_rotation" {
  rule = aws_cloudwatch_event_rule.spacelift_rotation.name
  arn  = aws_lambda_function.spacelift_rotation.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 3
  }

  dead_letter_config {
    arn = aws_sqs_queue.spacelift_rotation_delivery.arn
  }
}

resource "aws_lambda_permission" "spacelift_rotation" {
  statement_id  = "AllowExecutionFromEventBridgeSpaceliftRotation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.spacelift_rotation.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.spacelift_rotation.arn
}

resource "aws_cloudwatch_metric_alarm" "spacelift_session_token_stale" {
  alarm_name          = "hermes-spacelift-session-token-stale"
  alarm_description   = "The published Spacelift session token has less than the configured remaining lifetime, or no successful rotation has been recorded for two consecutive intervals. Spacelift reuses one fixed ten-hour expiry window per API key, so a rotation can succeed while publishing an expiring token; this alarm keys on the token's remaining life rather than on the function's exit status. Missing data is breaching because the metric is emitted on every successful rotation, so its absence is itself the failure."
  namespace           = local.spacelift_rotation_metric_namespace
  metric_name         = local.spacelift_rotation_metric_remaining
  statistic           = "Minimum"
  period              = local.spacelift_rotation_alarm_period
  evaluation_periods  = 2
  threshold           = var.hermes_spacelift_token_remaining_floor_seconds
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"

  dimensions = {
    SecretId = var.hermes_spacelift_session_token_secret_name
  }
}

resource "aws_cloudwatch_metric_alarm" "spacelift_rotation_errors" {
  alarm_name          = "hermes-spacelift-session-token-rotation-errors"
  alarm_description   = "The Spacelift session-token rotation function failed. The API key secret, the Spacelift GraphQL endpoint and the post-mint MCP verification are the only things it can fail on."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = local.spacelift_rotation_alarm_period
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.spacelift_rotation.function_name
  }
}

output "hermes_spacelift_session_token_secret_arn" {
  description = "ARN of the short-lived session-token secret. The gateway execution role's read allowlist in aws-mcp-boundary.tf must name exactly this secret and never the API key."
  value       = aws_secretsmanager_secret.spacelift_session_token.arn
}

output "hermes_spacelift_rotation_function_name" {
  description = "Name of the scheduled session-token rotation function."
  value       = aws_lambda_function.spacelift_rotation.function_name
}