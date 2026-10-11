output "hermes_mcp_endpoint" {
  description = "Custom HTTPS endpoint for the shared Hermes AgentCore Gateway; null until the upstream Gateway hostname is available."
  value       = local.hermes_mcp_enabled ? "https://${local.hermes_mcp_domain_name}/mcp" : null
}

output "oconnordev_site_deploy_role_arn" {
  description = "PRODUCTION site deploy role ARN; GitHub Actions reaches it through the TOOLS OIDC broker."
  value       = "arn:aws:iam::${local.accounts["PRODUCTION"]}:role/oconnordev-site-deploy"
}

output "oconnordev_cloudfront_distribution_id" {
  description = "CloudFront distribution ID to configure as the OCONNORDEV_CLOUDFRONT_DISTRIBUTION_ID repository variable."
  value       = var.oconnordev_cloudfront_distribution_id
}
output "dnssec_key_arn" {
  description = "Shared production DNSSEC signing key in us-east-1."
  value       = aws_kms_key.dnssec.arn
}
output "oconnordev_zone_id" {
  description = "Shared oconnor.dev zone retained for DNSSEC and the Hermes MCP endpoint."
  value       = aws_route53_zone.oconnordev.zone_id
}
output "oconnordev_certificate_arn" {
  description = "Validated wildcard certificate shared by resume and Hermes MCP, retained in production."
  value       = aws_acm_certificate_validation.oconnordev.certificate_arn
}
