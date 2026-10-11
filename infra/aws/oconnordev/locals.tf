locals {
  zone_name       = "oconnor.dev"
  web_bucket_name = "oconnordev-web"
  s3_origin_id    = "oconnordevS3Origin"
}

locals {
  accounts = jsondecode(file("${path.module}/../accounts.json"))

  tools_github_actions_broker_role_arn = "arn:aws:iam::${local.accounts["TOOLS"]}:role/oconnordev-github-actions-broker"
}
