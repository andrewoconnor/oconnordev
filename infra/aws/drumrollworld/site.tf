module "site" {
  source                  = "../../modules/static-site"
  name                    = "drumrollworld"
  domain_name             = local.zone_name
  bucket_name             = local.web_bucket_name
  origin_id               = local.s3_origin_id
  zone_id                 = aws_route53_zone.drumrollworld.zone_id
  broker_role_arn         = local.tools_github_actions_broker_role_arn
  content_security_policy = "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; script-src-attr 'none'; style-src 'self' 'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=' 'sha256-1OVkcrOQP7NV9SqPTIZQMVnSWqtceFiWV3g5XyDm98A=' 'sha256-9xjtvxMT1ApHlgn9ohbh2FNfvK5Tqtzy94BjfXBeMSY=' 'sha256-yfc2FhpkFR0EAy3T+zDsaAFGXSP9B3ELNvaJKDzNhkk=' 'sha256-GRFgt45UbKYCV14/Fqy6H9EB3zlAwSnH4xbsYt03Q6M='; style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
  error_responses = [for code in [403, 404] : {
    error_code            = code
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 10
  }]
  extra_deploy_statements = [{
    sid             = "PreserveExternalImages"
    effect          = "Deny"
    actions         = ["s3:DeleteObject"]
    object_suffixes = ["images/*"]
  }]
}
