locals {
  zone_name       = "oconnor.dev"
  web_bucket_name = "oconnordev-web"
  s3_origin_id    = "oconnordevS3Origin"
}

locals {
  accounts        = jsondecode(file("${path.module}/../accounts.json"))
  alert_topic_arn = "arn:aws:sns:us-east-1:${local.accounts["PRODUCTION"]}:oconnordev-alerts"

  tools_github_actions_broker_role_arn = "arn:aws:iam::${local.accounts["TOOLS"]}:role/oconnordev-github-actions-broker"
}
