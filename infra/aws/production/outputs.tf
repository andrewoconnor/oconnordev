output "hermes_mcp_endpoint" {
  description = "Custom HTTPS endpoint for the shared Hermes AgentCore Gateway; null until the upstream Gateway hostname is available."
  value       = local.hermes_mcp_enabled ? "https://${local.hermes_mcp_domain_name}/mcp" : null
}

output "oconnordev_site_deploy_role_arn" {
  description = "GitHub Actions OIDC role ARN for deploying apps/oconnordev on master."
  value       = aws_iam_role.github_actions_site_deploy.arn
}

output "oconnordev_cloudfront_distribution_id" {
  description = "CloudFront distribution ID to configure as the OCONNORDEV_CLOUDFRONT_DISTRIBUTION_ID repository variable."
  value       = aws_cloudfront_distribution.oconnordev.id
}
