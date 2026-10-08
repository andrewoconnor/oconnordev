locals {
  zone_name       = "drumroll.world"
  web_bucket_name = "drumrollworld-web"
  s3_origin_id    = "drumrollworldS3Origin"

  accounts = jsondecode(file("${path.module}/../accounts.json"))

  tools_github_actions_broker_role_arn = "arn:aws:iam::${local.accounts["TOOLS"]}:role/oconnordev-github-actions-broker"
}
