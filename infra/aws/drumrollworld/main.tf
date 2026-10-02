data "aws_kms_key" "dnssec" {
  key_id = "alias/dnssec"
}

resource "aws_route53_zone" "drumrollworld" {
  # checkov:skip=CKV2_AWS_39:Query logging would need a CloudWatch log group and pay per ingested byte, and a public zone's query log is high-volume and low-value for a personal domain whose records are all managed here.
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
  # checkov:skip=CKV_AWS_18:Access logging needs a second bucket plus a log-delivery bucket policy. This bucket holds only the static site, which is reproducible from the repository, and the extra bucket and its storage are not justified.
  # checkov:skip=CKV_AWS_144:Cross-region replication needs a replica bucket, an IAM replication role and versioned source objects. The bucket's content is deployed from this repository and is reproducible, so a second regional copy buys no recoverability.
  # checkov:skip=CKV_AWS_145:CloudFront reaches this bucket through an origin access control. An SSE-KMS bucket can only be read by CloudFront if a customer-managed key's policy grants the CloudFront service principal decrypt, and the AWS-managed aws/s3 key policy cannot be edited -- so SSE-KMS here would break the distribution rather than harden the bucket. SSE-S3 (AES256) is applied by aws_s3_bucket_server_side_encryption_configuration.web.
  # checkov:skip=CKV2_AWS_62:Event notifications need a consumer. Nothing consumes object-created events for this bucket; notifications would target a queue or function with no work to do.
  bucket = local.web_bucket_name

  tags = {
    Name = local.web_bucket_name
  }
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.web]
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

resource "aws_cloudfront_response_headers_policy" "drumrollworld" {
  name    = "drumrollworld-security-headers"
  comment = "Security response headers for the drumrollworld static site."

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