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
      API_KEY_SECRET_ID          = var.hermes_spacelift_api_key_secret_name
      TOKEN_SECRET_ID            = var.hermes_spacelift_session_token_secret_name
      TOKEN_JSON_KEY             = var.hermes_spacelift_session_token_json_key
      GRAPHQL_ENDPOINT           = local.spacelift_graphql_endpoint
      VERIFY_ENDPOINT            = var.hermes_spacelift_mcp_endpoint
      VERIFY_EXPECTED_TOOLS_JSON = local.spacelift_rotation_expected_tools
      METRIC_NAMESPACE           = local.spacelift_rotation_metric_namespace
      METRIC_REMAINING           = local.spacelift_rotation_metric_remaining
      HTTP_TIMEOUT_SECONDS       = tostring(var.hermes_spacelift_rotation_http_timeout_seconds)
    }
  }

  depends_on = [
    aws_servicequotas_service_quota.lambda_concurrent_executions,
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
  alarm_description   = "The published session token has less than the configured remaining lifetime, or no successful rotation check has been recorded for two consecutive intervals. The token lifetime is taken from the JWT exp claim on every run; no fixed provider lifetime is assumed. The alarm tracks remaining lifetime rather than invocation exit status."
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
