resource "aws_acm_certificate" "site" {
  count             = var.existing_certificate_arn == null ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  subject_alternative_names = [
    "*.${var.domain_name}"
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudfront_distribution" "site" {
  # checkov:skip=CKV_AWS_68:A WAF web ACL carries a fixed monthly cost per ACL and per rule. This distribution serves static objects from a private bucket with no dynamic surface, so the fixed cost is not justified; the bucket policy and origin access control are the access boundary.
  # checkov:skip=CKV_AWS_86:Access logs are intentionally disabled to avoid a second log bucket, its storage cost and the retained request metadata. Nothing reads them.
  # checkov:skip=CKV_AWS_310:Origin failover needs a second independent origin. The only origin is one S3 bucket reached by origin access control, which has no independent failover endpoint.
  # checkov:skip=CKV2_AWS_47:No WAF is attached by design, so there is no WAFv2 web ACL to configure with the AMR managed rule group.
  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
    origin_id                = var.origin_id
  }

  lifecycle {
    prevent_destroy = true
  }

  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"

  aliases = [
    var.domain_name,
    "www.${var.domain_name}"
  ]

  default_cache_behavior {
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    target_origin_id           = var.origin_id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site.id

    # AWS Managed-CachingOptimized (Gzip and Brotli cache keys).
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    viewer_protocol_policy = "redirect-to-https"
  }

  # Private S3 missing keys are often 403. This also masks origin denials.
  dynamic "custom_error_response" {
    for_each = var.error_responses
    content {
      error_code            = custom_error_response.value.error_code
      response_code         = custom_error_response.value.response_code
      response_page_path    = custom_error_response.value.response_page_path
      error_caching_min_ttl = custom_error_response.value.error_caching_min_ttl
    }
  }

  price_class = "PriceClass_100"

  restrictions {
    geo_restriction {
      restriction_type = "whitelist"
      locations        = ["US", "CA", "GB", "DE"]
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.existing_certificate_arn != null ? var.existing_certificate_arn : aws_acm_certificate_validation.site[0].certificate_arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = var.name
  description                       = "${var.name} S3 policy"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "site" {
  name    = "${var.name}-security-headers"
  comment = "Security response headers for the ${var.name} static site."

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
      content_security_policy = var.content_security_policy
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
  zone_id = var.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_route53_record.www.fqdn
    zone_id                = var.zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "site_validation" {
  for_each = {
    for dvo in try(aws_acm_certificate.site[0].domain_validation_options, []) : dvo.domain_name => {
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
  zone_id         = var.zone_id
}

resource "aws_acm_certificate_validation" "site" {
  count                   = var.existing_certificate_arn == null ? 1 : 0
  certificate_arn         = aws_acm_certificate.site[0].arn
  validation_record_fqdns = [for record in aws_route53_record.site_validation : record.fqdn]
}

resource "aws_route53_record" "www" {
  zone_id = var.zone_id
  name    = "www.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
resource "aws_route53_record" "apex_ipv6" {
  zone_id = var.zone_id
  name    = var.domain_name
  type    = "AAAA"
  alias {
    name                   = aws_route53_record.www_ipv6.fqdn
    zone_id                = var.zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "www_ipv6" {
  zone_id = var.zone_id
  name    = "www.${var.domain_name}"
  type    = "AAAA"
  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
