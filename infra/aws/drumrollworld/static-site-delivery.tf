resource "aws_acm_certificate" "drumrollworld" {
  domain_name       = local.zone_name
  validation_method = "DNS"

  subject_alternative_names = [
    "*.${local.zone_name}"
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudfront_distribution" "drumrollworld" {
  # checkov:skip=CKV_AWS_68:A WAF web ACL carries a fixed monthly cost per ACL and per rule. This distribution serves static objects from a private bucket with no dynamic surface, so the fixed cost is not justified; the bucket policy and origin access control are the access boundary.
  # checkov:skip=CKV_AWS_86:Access logs are intentionally disabled to avoid a second log bucket, its storage cost and the retained request metadata. Nothing reads them.
  # checkov:skip=CKV_AWS_310:Origin failover needs a second independent origin. The only origin is one S3 bucket reached by origin access control, which has no independent failover endpoint.
  # checkov:skip=CKV2_AWS_47:No WAF is attached by design, so there is no WAFv2 web ACL to configure with the AMR managed rule group.
  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.drumrollworld.id
    origin_id                = local.s3_origin_id
  }

  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"

  aliases = [
    local.zone_name,
    "www.${local.zone_name}"
  ]

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    target_origin_id           = local.s3_origin_id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.drumrollworld.id

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400
  }

  # Publish /404.html before applying. Private S3 without ListBucket returns
  # 403 for missing keys; this also masks genuine origin permission denials.
  # Keep a real 404 (not an SPA fallback) for both S3 missing-object responses.
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 10
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 10
  }

  price_class = "PriceClass_100"

  restrictions {
    geo_restriction {
      restriction_type = "whitelist"
      locations        = ["US", "CA", "GB", "DE"]
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.drumrollworld.certificate_arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }
}

resource "aws_cloudfront_origin_access_control" "drumrollworld" {
  name                              = "drumrollworld"
  description                       = "drumrollworld S3 policy"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "drumrollworld" {
  name    = "drumrollworld-security-headers"
  comment = "Security response headers for the drumrollworld static site."

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      override = true
      value    = "accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()"
    }
  }

  security_headers_config {
    # Owned Basis is compiled with DYNAMIC_EXECUTION=0; only WASM compilation
    # is allowed in inherited-CSP blob workers, never JavaScript string execution.
    content_security_policy {
      content_security_policy = "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; script-src-attr 'none'; style-src 'self' 'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=' 'sha256-1OVkcrOQP7NV9SqPTIZQMVnSWqtceFiWV3g5XyDm98A=' 'sha256-9xjtvxMT1ApHlgn9ohbh2FNfvK5Tqtzy94BjfXBeMSY=' 'sha256-yfc2FhpkFR0EAy3T+zDsaAFGXSP9B3ELNvaJKDzNhkk=' 'sha256-GRFgt45UbKYCV14/Fqy6H9EB3zlAwSnH4xbsYt03Q6M='; style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
      override                = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }

    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

resource "aws_route53_record" "apex" {
  zone_id = aws_route53_zone.drumrollworld.zone_id
  name    = local.zone_name
  type    = "A"

  alias {
    name                   = aws_route53_record.www.fqdn
    zone_id                = aws_route53_zone.drumrollworld.zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "drumrollworld_validation" {
  for_each = {
    for dvo in aws_acm_certificate.drumrollworld.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
    if length(regexall("\\*\\..+", dvo.domain_name)) > 0
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = aws_route53_zone.drumrollworld.id
}

resource "aws_acm_certificate_validation" "drumrollworld" {
  certificate_arn         = aws_acm_certificate.drumrollworld.arn
  validation_record_fqdns = [for record in aws_route53_record.drumrollworld_validation : record.fqdn]
}

resource "aws_route53_record" "www" {
  zone_id = aws_route53_zone.drumrollworld.zone_id
  name    = "www.${local.zone_name}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.drumrollworld.domain_name
    zone_id                = aws_cloudfront_distribution.drumrollworld.hosted_zone_id
    evaluate_target_health = false
  }
}