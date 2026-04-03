variable "spacelift_run_id" {}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.39.0"
    }
  }
}

provider "aws" {
  assume_role {
    role_arn     = "arn:aws:iam::767397796791:role/spacelift"
    session_name = var.spacelift_run_id
    external_id  = "spacelift-general"
  }

  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

locals {
  zone_name       = "drumroll.world"
  web_bucket_name = "drumrollworld-web"
  s3_origin_id    = "drumrollworldS3Origin"
}

data "aws_kms_key" "dnssec" {
  key_id = "alias/dnssec"
}

resource "aws_route53_zone" "drumrollworld" {
  name = local.zone_name
}

resource "aws_route53_key_signing_key" "drumrollworld" {
  hosted_zone_id             = aws_route53_zone.drumrollworld.id
  key_management_service_arn = data.aws_kms_key.dnssec.arn
  name                       = local.zone_name
}

resource "aws_route53_hosted_zone_dnssec" "drumrollworld" {
  depends_on = [
    aws_route53_key_signing_key.drumrollworld
  ]
  hosted_zone_id = aws_route53_key_signing_key.drumrollworld.hosted_zone_id
}

resource "aws_s3_bucket" "web" {
  bucket = local.web_bucket_name

  tags = {
    Name = local.web_bucket_name
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket = aws_s3_bucket.web.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "web_tls" {
  statement {
    sid = "Enforce TLS"

    effect = "Deny"

    actions = [
      "s3:*"
    ]

    resources = [
      aws_s3_bucket.web.arn,
      "${aws_s3_bucket.web.arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }

    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }

  statement {
    sid = "AllowCloudFrontServicePrincipal"

    effect = "Allow"

    actions = [
      "s3:GetObject"
    ]

    resources = [
      "${aws_s3_bucket.web.arn}/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.drumrollworld.arn]
    }

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
  }
}

resource "aws_s3_bucket_policy" "web_tls" {
  bucket = aws_s3_bucket.web.id

  policy = data.aws_iam_policy_document.web_tls.json
}

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

resource "aws_route53_record" "drumrollworld_validation" {
  for_each = {
    for dvo in aws_acm_certificate.drumrollworld.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
   # Skips the domain if it doesn't contain a wildcard
    if length(regexall("\\*\\..+", dvo.domain_name)) > 0
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = aws_route53_zone.drumrollworld.id
}

resource "aws_cloudfront_origin_access_control" "drumrollworld" {
  name                              = "drumrollworld"
  description                       = "drumrollworld S3 policy"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "drumrollworld" {
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
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = local.s3_origin_id

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
    acm_certificate_arn      = aws_acm_certificate.drumrollworld.arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }
}

#resource "aws_route53_record" "www" {
#  zone_id = aws_route53_zone.drumrollworld.zone_id
#  name    = "www.${local.zone_name}"
#  type    = "A"
#
#  alias {
#    name                   = aws_cloudfront_distribution.drumrollworld.domain_name
#    zone_id                = aws_cloudfront_distribution.drumrollworld.hosted_zone_id
#    evaluate_target_health = false
#  }
#}

resource "aws_route53_record" "www" {
  zone_id = aws_route53_zone.drumrollworld.zone_id
  name    = "www.${local.zone_name}"
  type    = "A"

  # Standard records require a TTL (Time To Live)
  ttl     = 300
  records = ["1.1.1.1"]
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
