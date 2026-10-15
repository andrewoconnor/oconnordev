
variable "hermes_gateway_log_retention_days" {
  description = "Retention in days for the AgentCore gateway application log group."
  type        = number
  default     = 7

  validation {
    condition = contains([
      1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180,
      365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653,
    ], var.hermes_gateway_log_retention_days)
    error_message = "hermes_gateway_log_retention_days must be one of the retention values CloudWatch Logs accepts."
  }
}

locals {
  hermes_gateway_log_group_name = "/aws/vendedlogs/bedrock-agentcore/gateway/hermes"
}

resource "aws_cloudwatch_log_group" "gateway_application_logs" {
  # checkov:skip=CKV_AWS_158:Encrypted at rest with the default AWS-owned key. An AWS-managed key cannot be referenced here -- alias/aws/logs is created lazily by the service and does not resolve beforehand -- and a customer-managed key would need a key policy granting the log-delivery service kms:GenerateDataKey*, where a policy wrong in either direction fails the delivery silently rather than loudly.
  # checkov:skip=CKV_AWS_338:Historical MCP request/response bodies retain the existing seven-day default expiry, not a year. Disabling delivery is not a retroactive purge; preserve this group and its retention unchanged.
  name              = local.hermes_gateway_log_group_name
  retention_in_days = var.hermes_gateway_log_retention_days
}

resource "aws_cloudwatch_log_delivery_source" "gateway_application_logs" {
  name         = "hermes-gateway-application-logs"
  log_type     = "APPLICATION_LOGS"
  resource_arn = aws_bedrockagentcore_gateway.hermes.gateway_arn
}

resource "aws_cloudwatch_log_delivery_destination" "gateway_application_logs" {
  name = "hermes-gateway-application-logs"

  delivery_destination_configuration {
    destination_resource_arn = aws_cloudwatch_log_group.gateway_application_logs.arn
  }
}

# APPLICATION_LOGS delivery is intentionally absent: Gateway vended logs include
# MCP request/response bodies. Retain inert source/destination metadata and the
# historical log group (seven-day default expiry), not a replacement payload sink.
# Native metrics and the UserErrors alarm below do not depend on this delivery.
# Owner apply/live verification: docs/runbooks/gateway-log-privacy.md.

resource "aws_cloudwatch_metric_alarm" "gateway_user_errors" {
  alarm_name          = "hermes-gateway-user-errors"
  alarm_description   = "Repeated AgentCore Gateway 4xx responses, including rejected authentication or policy decisions."
  namespace           = "AWS/Bedrock-AgentCore"
  metric_name         = "UserErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Resource = aws_bedrockagentcore_gateway.hermes.gateway_arn
  }
}
