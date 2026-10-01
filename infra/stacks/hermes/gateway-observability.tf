
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
  # checkov:skip=CKV_AWS_338:Retention is deliberately 7 days, not a year. These are high-volume diagnostic records carrying MCP request and response bodies, kept to debug an active problem rather than as an audit trail, and the shorter retention bounds their storage. Raise var.hermes_gateway_log_retention_days to keep them longer.
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

resource "aws_cloudwatch_log_delivery" "gateway_application_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway_application_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway_application_logs.arn
}