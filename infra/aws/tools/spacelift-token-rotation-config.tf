variable "hermes_spacelift_rotation_interval_minutes" {
  description = "Poll for an observed JWT expiry advance every 15 minutes by default; use a shorter interval for diagnosis. The function derives lifetime from exp and never waits inside Lambda."
  type        = number
  default     = 15

  validation {
    condition     = var.hermes_spacelift_rotation_interval_minutes >= 1 && var.hermes_spacelift_rotation_interval_minutes <= 15 && floor(var.hermes_spacelift_rotation_interval_minutes) == var.hermes_spacelift_rotation_interval_minutes
    error_message = "hermes_spacelift_rotation_interval_minutes must be a whole number of minutes between 1 and 15."
  }
}

variable "hermes_spacelift_token_remaining_floor_seconds" {
  description = "Alert when the published session token has less than this remaining lifetime. A successful rotation still alarms when it publishes a nearly-expired token."
  type        = number
  default     = 7200

  validation {
    condition     = var.hermes_spacelift_token_remaining_floor_seconds >= 60 && var.hermes_spacelift_token_remaining_floor_seconds <= 86400
    error_message = "hermes_spacelift_token_remaining_floor_seconds must be between 60 and 86400 seconds."
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
  description = "Maximum timeout for each rotation HTTP request; runtime clamps it to Lambda's remaining execution time with a safety margin."
  type        = number
  default     = 5

  validation {
    condition     = var.hermes_spacelift_rotation_http_timeout_seconds >= 1 && var.hermes_spacelift_rotation_http_timeout_seconds <= 10 && floor(var.hermes_spacelift_rotation_http_timeout_seconds) == var.hermes_spacelift_rotation_http_timeout_seconds
    error_message = "hermes_spacelift_rotation_http_timeout_seconds must be a whole number of seconds between 1 and 10."
  }
}

locals {
  spacelift_rotation_function_name    = "hermes-spacelift-session-token-rotation"
  spacelift_rotation_metric_namespace = "Hermes/SpaceliftAuth"
  spacelift_rotation_metric_remaining = "SessionTokenRemainingSeconds"
  spacelift_rotation_expected_tools   = jsonencode(sort(tolist(local.spacelift_native_tools)))
  spacelift_rotation_schedule         = "rate(${var.hermes_spacelift_rotation_interval_minutes} ${var.hermes_spacelift_rotation_interval_minutes == 1 ? "minute" : "minutes"})"
  spacelift_rotation_alarm_period     = var.hermes_spacelift_rotation_interval_minutes * 60
  spacelift_rotation_source_dir       = "${local.repo_root}/infra/aws/tools/lambdas/spacelift_session_token"
  spacelift_rotation_archive          = "${path.module}/.terraform-archives/spacelift_session_token.zip"
  spacelift_host                      = split("/", replace(var.hermes_spacelift_mcp_endpoint, "https://", ""))[0]
  spacelift_graphql_endpoint          = "https://${local.spacelift_host}/graphql"
}

data "archive_file" "spacelift_rotation" {
  type        = "zip"
  source_dir  = local.spacelift_rotation_source_dir
  output_path = local.spacelift_rotation_archive
  excludes    = ["test_*.py", "test/**", "**/__pycache__/**", "**/*.pyc"]
}
