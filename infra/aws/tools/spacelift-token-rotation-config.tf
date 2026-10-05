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
  excludes    = ["test/**", "**/__pycache__/**", "**/*.pyc"]
}
