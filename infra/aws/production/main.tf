variable "spacelift_run_id" {
  type = string
}

terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.66.0"
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
  zone_name       = "oconnor.dev"
  web_bucket_name = "oconnordev-web"
  s3_origin_id    = "oconnordevS3Origin"
}

resource "aws_route53_zone" "oconnordev" {
  # checkov:skip=CKV2_AWS_39:Query logging would need a CloudWatch log group and pay per ingested byte, and a public zone's query log is high-volume and low-value for a personal domain whose records are all managed here.
  name = local.zone_name
}

data "aws_iam_policy_document" "dnssec" {
  # checkov:skip=CKV_AWS_109:Key policy, not an IAM identity policy. The Resource element in a KMS key policy is always "*" because the policy is attached to exactly one key, so the wildcard is not a cross-resource grant -- AWS's own example key policy and the KMS console's default both use "Resource": "*". The root-account statement mirrors the console default (EnableIAMUserPermissions) and is what lets IAM policies delegate access to this key at all.
  # checkov:skip=CKV_AWS_111:Key policy, not an IAM identity policy. The only unconditional statement is the account-root grant that every KMS key policy carries; the Route 53 DNSSEC statements are already constrained by aws:SourceAccount and kms:GrantIsForAWSResource conditions.
  # checkov:skip=CKV_AWS_356:Key policy, not an IAM identity policy. "Resource": "*" in a key policy denotes the single key the policy is attached to. Rewriting this as aws_kms_key_policy scoped to the key ARN would not change what the policy permits and would risk an in-place policy update on the live signing key that Route 53 DNSSEC depends on.
  statement {
    effect = "Allow"

    actions = [
      "kms:*"
    ]

    resources = [
      "*"
    ]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid = "Allow Route 53 DNSSEC Service"

    effect = "Allow"

    actions = [
      "kms:DescribeKey",
      "kms:GetPublicKey",
      "kms:Sign"
    ]

    resources = [
      "*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    principals {
      type        = "Service"
      identifiers = ["dnssec-route53.amazonaws.com"]
    }
  }

  statement {
    sid = "Allow Route 53 DNSSEC to CreateGrant"

    effect = "Allow"

    actions = [
      "kms:CreateGrant"
    ]

    resources = [
      "*"
    ]

    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }

    principals {
      type        = "Service"
      identifiers = ["dnssec-route53.amazonaws.com"]
    }
  }
}

resource "aws_kms_key" "dnssec" {
  description              = "Asymmetric KMS key with ECC_NIST_P256 for DNSSEC"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 7

  policy = data.aws_iam_policy_document.dnssec.json
}

resource "aws_kms_alias" "dnssec" {
  name          = "alias/dnssec"
  target_key_id = aws_kms_key.dnssec.key_id
}

resource "aws_route53_key_signing_key" "oconnordev" {
  hosted_zone_id             = aws_route53_zone.oconnordev.id
  key_management_service_arn = aws_kms_key.dnssec.arn
  name                       = local.zone_name
}

resource "aws_route53_hosted_zone_dnssec" "oconnordev" {
  depends_on = [
    aws_route53_key_signing_key.oconnordev
  ]
  hosted_zone_id = aws_route53_key_signing_key.oconnordev.hosted_zone_id
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

# Bounds the storage that versioning adds: superseded objects are the only ones
# that accumulate, because a deploy writes a new version rather than editing in
# place.
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
      values   = [aws_cloudfront_distribution.oconnordev.arn]
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

resource "aws_route53_record" "oconnordev_validation" {
  for_each = {
    for dvo in aws_acm_certificate.oconnordev.domain_validation_options : dvo.domain_name => {
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
  zone_id         = aws_route53_zone.oconnordev.id
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
    acm_certificate_arn      = aws_acm_certificate.oconnordev.arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }
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
