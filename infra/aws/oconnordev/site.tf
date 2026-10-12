module "site" {
  existing_certificate_arn = var.site_certificate_arn
  source                   = "../../modules/static-site"
  name                     = "oconnordev"
  domain_name              = local.zone_name
  bucket_name              = local.web_bucket_name
  origin_id                = local.s3_origin_id
  zone_id                  = var.site_zone_id
  broker_role_arn          = local.tools_github_actions_broker_role_arn
  content_security_policy  = "default-src 'none'; script-src 'sha256-4JHmSUmc1wePxlVTxsVTwn6GgpQ+Oa79jBlKuyYIE5c='; script-src-attr 'none'; style-src 'self'; style-src-attr 'none'; img-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
  error_responses = [for code in [403, 404] : {
    error_code            = code
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 10
  }]
}
