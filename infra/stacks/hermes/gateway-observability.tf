# AgentCore gateway application logging.
#
# AgentCore ships no gateway logs by default: the service writes nothing to
# CloudWatch until an account-level log delivery is configured. Without this,
# a failed tool invocation leaves no server-side trace at all — the gateway
# returns a generic error and the reason is only visible in the service's own
# logs, which do not exist.
#
# This delivers the gateway's APPLICATION_LOGS records to CloudWatch Logs.
# Those records carry the MCP request and response bodies and the per-request
# error flag, which is what makes a failed tool call diagnosable.

variable "hermes_gateway_log_retention_days" {
  description = "Retention in days for the AgentCore gateway application log group."
  type        = number
  default     = 365

  # CloudWatch Logs accepts a fixed set of retention values, not an arbitrary
  # range, so the constraint is an allow-list rather than a numeric bound.
  validation {
    condition = contains([
      1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180,
      365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653,
    ], var.hermes_gateway_log_retention_days)
    error_message = "hermes_gateway_log_retention_days must be one of the retention values CloudWatch Logs accepts."
  }
}

locals {
  # Vended log delivery requires the destination log group to live under
  # /aws/vendedlogs/. This mirrors the name AgentCore's console uses by
  # default, so the group is also where the console would expect to find it.
  hermes_gateway_log_group_name = "/aws/vendedlogs/bedrock-agentcore/gateway/APPLICATION_LOGS/${aws_bedrockagentcore_gateway.hermes.gateway_id}"
}

resource "aws_cloudwatch_log_group" "gateway_application_logs" {
  name              = local.hermes_gateway_log_group_name
  retention_in_days = var.hermes_gateway_log_retention_days

  # The AWS-managed CloudWatch Logs key rather than a customer-managed one.
  # AWS-managed keys are created lazily, so `alias/aws/logs` does not resolve
  # until the service has used it once.
  kms_key_id = "alias/aws/logs"
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

# Deliberately does not set `record_fields`. The delivery's log source has
# mandatory fields that must appear in that list when it is supplied, and the
# set of mandatory fields is not published — an incomplete list is rejected.
# Omitting it delivers the whole record, which is what retains the MCP request
# and response bodies and the error flag. Narrowing it later is possible once
# the mandatory set is known; see the README.
resource "aws_cloudwatch_log_delivery" "gateway_application_logs" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway_application_logs.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway_application_logs.arn
}