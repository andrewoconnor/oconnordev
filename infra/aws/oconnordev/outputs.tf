output "oconnordev_site_deploy_role_arn" {
  description = "Existing resume deploy role reached through the TOOLS broker."
  value       = module.site.deploy_role_arn
}
output "oconnordev_cloudfront_distribution_id" {
  description = "Existing resume CloudFront distribution ID for invalidations."
  value       = module.site.distribution_id
}
