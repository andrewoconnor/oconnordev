resource "github_actions_variable" "site_deploy_role_arn" {
  repository    = "oconnordev"
  variable_name = "OCONNORDEV_SITE_DEPLOY_ROLE_ARN"
  value         = var.oconnordev_site_deploy_role_arn
}

resource "github_actions_variable" "cloudfront_distribution_id" {
  repository    = "oconnordev"
  variable_name = "OCONNORDEV_CLOUDFRONT_DISTRIBUTION_ID"
  value         = var.oconnordev_cloudfront_distribution_id
}
