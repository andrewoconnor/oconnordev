data "aws_caller_identity" "current" {}

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

resource "aws_kms_alias" "dnssec" {
  name          = "alias/dnssec"
  target_key_id = aws_kms_key.dnssec.key_id
}

resource "aws_kms_key" "dnssec" {
  description              = "Asymmetric KMS key with ECC_NIST_P256 for DNSSEC"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 7

  policy = data.aws_iam_policy_document.dnssec.json
}

resource "aws_route53_hosted_zone_dnssec" "oconnordev" {
  depends_on = [
    aws_route53_key_signing_key.oconnordev
  ]
  hosted_zone_id = aws_route53_key_signing_key.oconnordev.hosted_zone_id
}

resource "aws_route53_key_signing_key" "oconnordev" {
  hosted_zone_id             = aws_route53_zone.oconnordev.id
  key_management_service_arn = aws_kms_key.dnssec.arn
  name                       = local.zone_name
}

resource "aws_route53_zone" "oconnordev" {
  # checkov:skip=CKV2_AWS_39:Query logging would need a CloudWatch log group and pay per ingested byte, and a public zone's query log is high-volume and low-value for a personal domain whose records are all managed here.
  name = local.zone_name
}