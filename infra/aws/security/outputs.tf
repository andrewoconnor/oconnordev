output "config_aggregator_name" {
  description = "Name of the organization-wide Config aggregator."
  value       = aws_config_configuration_aggregator.organization.name
}

output "config_audit_bucket_name" {
  description = "Name of the central Config bucket. Delivery channels in GENERAL, PRODUCTION and HERMES point at this name."
  value       = aws_s3_bucket.config.id
}

output "config_audit_bucket_arn" {
  description = "ARN of the central Config bucket."
  value       = aws_s3_bucket.config.arn
}

output "cloudtrail_audit_bucket_name" {
  description = "Name of the organization CloudTrail log bucket."
  value       = aws_s3_bucket.cloudtrail.id
}

output "cloudtrail_audit_bucket_arn" {
  description = "ARN of the organization CloudTrail log bucket."
  value       = aws_s3_bucket.cloudtrail.arn
}

output "security_gateway_id" {
  description = "Gateway ID of the security account's AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.security.gateway_id
}

output "security_gateway_arn" {
  description = "ARN of the security account's AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.security.gateway_arn
}

output "security_gateway_url" {
  description = "MCP endpoint of the security account's gateway, consumed by the Hermes gateway target."
  value       = aws_bedrockagentcore_gateway.security.gateway_url
}

output "aws_account_id" {
  description = "AWS account ID reached by the security stack's Spacelift role."
  value       = data.aws_caller_identity.current.account_id
}
