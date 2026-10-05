resource "aws_acm_certificate" "oconnordev" {
  domain_name       = local.zone_name
  validation_method = "DNS"

  subject_alternative_names = [
    "*.${local.zone_name}"
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudfront_distribution" "oconnordev" {
  # checkov:skip=CKV_AWS_68:A WAF web ACL carries a fixed monthly cost per ACL and per rule. This distribution serves static objects from a private bucket with no dynamic surface, so the fixed cost is not justified; the bucket policy and origin access control are the access boundary.
  # checkov:skip=CKV_AWS_86:Access logs are intentionally disabled to avoid a second log bucket, its storage cost and the retained request metadata. Nothing reads them.
  # checkov:skip=CKV_AWS_310:Origin failover needs a second independent origin. The only origin is one S3 bucket reached by origin access control, which has no independent failover endpoint.
  # checkov:skip=CKV2_AWS_47:No WAF is attached by design, so there is no WAFv2 web ACL to configure with the AMR managed rule group.
  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.oconnordev.id
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
    target_origin_id           = local.s3_origin_id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.oconnordev.id

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

  price_class = "PriceClass_100"

  restrictions {
    geo_restriction {
      restriction_type = "whitelist"
      locations        = ["US", "CA", "GB", "DE"]
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.oconnordev.certificate_arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }
}

resource "aws_cloudfront_origin_access_control" "oconnordev" {
  name                              = "oconnordev"
  description                       = "oconnordev S3 policy"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "oconnordev" {
  name    = "oconnordev-security-headers"
  comment = "Security response headers for the oconnordev static site."

  security_headers_config {
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
  zone_id = aws_route53_zone.oconnordev.zone_id
  name    = local.zone_name
  type    = "A"

  alias {
    name                   = aws_route53_record.www.fqdn
    zone_id                = aws_route53_zone.oconnordev.zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "oconnordev_validation" {
  for_each = {
    for dvo in aws_acm_certificate.oconnordev.domain_validation_options : dvo.domain_name => {
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
  zone_id         = aws_route53_zone.oconnordev.id
}

resource "aws_acm_certificate_validation" "oconnordev" {
  certificate_arn         = aws_acm_certificate.oconnordev.arn
  validation_record_fqdns = [for record in aws_route53_record.oconnordev_validation : record.fqdn]
}

resource "aws_route53_record" "www" {
  zone_id = aws_route53_zone.oconnordev.zone_id
  name    = "www.${local.zone_name}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.oconnordev.domain_name
    zone_id                = aws_cloudfront_distribution.oconnordev.hosted_zone_id
    evaluate_target_health = false
  }
}
