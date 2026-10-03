locals {
  zone_name       = "oconnor.dev"
  web_bucket_name = "oconnordev-web"
  s3_origin_id    = "oconnordevS3Origin"
}

locals {
  accounts = jsondecode(file("${path.module}/../accounts.json"))
}
