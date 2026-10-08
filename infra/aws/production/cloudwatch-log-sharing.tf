# Empty until the security stack's dependency output resolves. This gate
# prevents first-apply failures; Spacelift wires the sink ARN automatically.
variable "security_logs_sink_arn" {
  description = "Security account's us-east-1 CloudWatch OAM sink ARN, supplied by Spacelift."
  type        = string
  default     = ""

  validation {
    condition = var.security_logs_sink_arn == "" || can(regex(
      "^arn:aws:oam:us-east-1:${local.accounts["SECURITY"]}:sink/[0-9a-f-]+$",
      var.security_logs_sink_arn,
    ))
    error_message = "The sink must be in the SECURITY account in us-east-1, or empty while its dependency is unresolved."
  }
}

resource "aws_oam_link" "security_logs" {
  count = var.security_logs_sink_arn != "" ? 1 : 0

  label_template  = "oconnordev-production"
  resource_types  = ["AWS::Logs::LogGroup"]
  sink_identifier = var.security_logs_sink_arn
  # No log-group filter: share every existing and future log group in this
  # account/region. No metrics, traces, replication, or retention changes.
}

output "security_logs_link_arn" {
  description = "Source link to the security log sink; null until its dependency resolves."
  value       = one(aws_oam_link.security_logs[*].arn)
}
