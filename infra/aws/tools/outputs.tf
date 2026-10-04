output "aws_account_id" {
  description = "AWS account ID reached by the TOOLS stack's Spacelift role."
  value       = data.aws_caller_identity.current.account_id
}

output "hermes_spacelift_mcp_endpoint" {
  description = "Narrowed Spacelift MCP endpoint fronted by the shared gateway."
  value       = var.hermes_spacelift_mcp_endpoint
}

output "hermes_spacelift_target_name" {
  description = "Gateway target name that prefixes the Spacelift MCP tools."
  value       = local.spacelift_target_name
}

output "hermes_spacelift_session_token_secret_arn" {
  description = "ARN of the short-lived session-token secret. The gateway execution role's read allowlist in target-aws.tf must name exactly this secret and never the API key."
  value       = aws_secretsmanager_secret.spacelift_session_token.arn
}

output "hermes_spacelift_rotation_function_name" {
  description = "Name of the scheduled session-token rotation function."
  value       = aws_lambda_function.spacelift_rotation.function_name
}

output "hermes_cognito_issuer" {
  description = "Cognito OIDC issuer used by the AgentCore JWT authorizer."
  value       = local.cognito_issuer
}

output "hermes_cognito_token_url" {
  description = "Cognito OAuth client-credentials token endpoint for the local adapter."
  value       = local.cognito_token_url
}

output "hermes_cognito_client_id" {
  description = "Non-secret Cognito M2M app client ID."
  value       = aws_cognito_user_pool_client.hermes.id
}

output "hermes_cognito_scope" {
  description = "The single OAuth scope accepted by the AgentCore Gateway."
  value       = local.gateway_scope
}

output "hermes_aws_mcp_target_name" {
  description = "Gateway target name that prefixes the AWS MCP tools."
  value       = local.hermes_aws_target_name
}

output "tools_gateway_origin_hostname" {
  description = "AgentCore Gateway hostname exported by the TOOLS account stack for the production CloudFront endpoint."
  value       = split("/", trimprefix(aws_bedrockagentcore_gateway.hermes.gateway_url, "https://"))[0]
}

output "hermes_gateway_origin_hostname" {
  description = "Deprecated compatibility alias for tools_gateway_origin_hostname; retained for external consumers during migration."
  value       = split("/", trimprefix(aws_bedrockagentcore_gateway.hermes.gateway_url, "https://"))[0]
}

output "tools_github_actions_broker_role_arn" {
  description = "TOOLS account GitHub Actions OIDC broker role ARN, permitted to assume only the PRODUCTION site deploy role."
  value       = aws_iam_role.github_actions_broker.arn
}
