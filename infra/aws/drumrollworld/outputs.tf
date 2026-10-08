output "drumrollworld_site_deploy_role_arn" {
  description = "DrumrollWorld deploy role in PRODUCTION, reached through the TOOLS OIDC broker."
  value       = aws_iam_role.github_actions_site_deploy.arn
}

output "drumrollworld_cloudfront_distribution_id" {
  description = "Existing DrumrollWorld CloudFront distribution ID for deployment invalidations."
  value       = aws_cloudfront_distribution.drumrollworld.id
}
