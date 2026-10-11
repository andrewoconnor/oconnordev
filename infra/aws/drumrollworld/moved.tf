moved {
  from = aws_acm_certificate.drumrollworld
  to   = module.site.aws_acm_certificate.site[0]
}

moved {
  from = aws_cloudfront_distribution.drumrollworld
  to   = module.site.aws_cloudfront_distribution.site
}

moved {
  from = aws_cloudfront_origin_access_control.drumrollworld
  to   = module.site.aws_cloudfront_origin_access_control.site
}

moved {
  from = aws_cloudfront_response_headers_policy.drumrollworld
  to   = module.site.aws_cloudfront_response_headers_policy.site
}

moved {
  from = aws_route53_record.apex
  to   = module.site.aws_route53_record.apex
}

moved {
  from = aws_route53_record.drumrollworld_validation
  to   = module.site.aws_route53_record.site_validation
}

moved {
  from = aws_acm_certificate_validation.drumrollworld
  to   = module.site.aws_acm_certificate_validation.site[0]
}

moved {
  from = aws_route53_record.www
  to   = module.site.aws_route53_record.www
}

moved {
  from = aws_s3_bucket.web
  to   = module.site.aws_s3_bucket.web
}

moved {
  from = aws_s3_bucket_lifecycle_configuration.web
  to   = module.site.aws_s3_bucket_lifecycle_configuration.web
}

moved {
  from = aws_s3_bucket_policy.web_tls
  to   = module.site.aws_s3_bucket_policy.web_tls
}

moved {
  from = aws_s3_bucket_public_access_block.web
  to   = module.site.aws_s3_bucket_public_access_block.web
}

moved {
  from = aws_s3_bucket_server_side_encryption_configuration.web
  to   = module.site.aws_s3_bucket_server_side_encryption_configuration.web
}

moved {
  from = aws_s3_bucket_versioning.web
  to   = module.site.aws_s3_bucket_versioning.web
}

moved {
  from = aws_iam_role.github_actions_site_deploy
  to   = module.site.aws_iam_role.github_actions_site_deploy
}

moved {
  from = aws_iam_role_policy.github_actions_site_deploy
  to   = module.site.aws_iam_role_policy.github_actions_site_deploy
}
