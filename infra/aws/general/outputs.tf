output "cloudtrail_trail_arn" {
  description = "ARN of the organization trail. Carries the management account ID, because the management account owns the trail. Mirrored as a literal in the CloudTrail bucket policy's aws:SourceArn condition in the security stack."
  value       = local.cloudtrail_trail_arn
}

output "cloudtrail_organization_log_prefix" {
  description = "S3 key prefix under which each account's organization-trail logs are delivered."
  value       = "AWSLogs/${local.accounts["ORGANIZATION"]}/"
}

output "cloudtrail_management_account_fallback_prefix" {
  description = "S3 key prefix CloudTrail falls back to if the organization trail is ever converted to a single-account trail for the management account."
  value       = "AWSLogs/${data.aws_caller_identity.current.account_id}/"
}

output "cloudtrail_organization_trail_created" {
  description = "Whether the organization trail exists. False until enable_management_account_audit is set to true."
  value       = var.enable_management_account_audit
}

output "config_recording_enabled" {
  description = "Whether the management account's Config recorder is configured and delivering to the central Config bucket."
  value       = var.enable_management_account_audit
}
