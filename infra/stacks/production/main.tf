variable "spacelift_run_id" {}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50.0"
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

locals {
  zone_name       = "oconnor.dev"
  web_bucket_name = "oconnordev-web"
}

resource "aws_route53_zone" "oconnordev" {
  name = local.zone_name
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
}

resource "aws_s3_bucket_policy" "web_tls" {
  bucket = aws_s3_bucket.web.id

  policy = data.aws_iam_policy_document.web_tls.json
}
