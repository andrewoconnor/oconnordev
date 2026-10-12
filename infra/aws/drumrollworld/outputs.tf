output "drumrollworld_site_deploy_role_arn" {
  description = "DrumrollWorld deploy role in PRODUCTION, reached through the TOOLS OIDC broker."
  value       = module.site.deploy_role_arn
}

output "drumrollworld_cloudfront_distribution_id" {
  description = "Existing DrumrollWorld CloudFront distribution ID for deployment invalidations."
  value       = module.site.distribution_id
}
