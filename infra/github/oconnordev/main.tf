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

resource "github_actions_variable" "tools_github_actions_broker_role_arn" {
  repository    = "oconnordev"
  variable_name = "OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN"
  value         = var.oconnordev_tools_github_actions_broker_role_arn
}
