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
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
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
