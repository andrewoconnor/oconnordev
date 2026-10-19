data "aws_iam_policy_document" "outlook_signing_key" {
  # checkov:skip=CKV_AWS_109:Key policy, not an IAM identity policy. Resource "*" is the one key this policy is attached to; the root statement only delegates access to IAM policies.
  # checkov:skip=CKV_AWS_111:Key policy, not an IAM identity policy. The account-root grant is the standard statement that lets IAM policies grant kms:Sign.
  # checkov:skip=CKV_AWS_356:Key policy, not an IAM identity policy. Resource "*" in a key policy denotes this key only.
  statement {
    sid       = "AccountAdministersKey"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "outlook_signing" {
  # checkov:skip=CKV_AWS_7:KMS cannot rotate asymmetric keys; the Entra certificate pins this key.
  description              = "Signs AgentCore PRIVATE_KEY_JWT client assertions for the Outlook Entra app."
  customer_master_key_spec = "RSA_2048"
  key_usage                = "SIGN_VERIFY"
  deletion_window_in_days  = 30
  policy                   = data.aws_iam_policy_document.outlook_signing_key.json
}

resource "aws_kms_alias" "outlook_signing" {
  name          = "alias/hermes-outlook-oauth-signing"
  target_key_id = aws_kms_key.outlook_signing.key_id
}

output "outlook_signing_key_arn" {
  description = "Run scripts/bootstrap/outlook/build_certificate.py with this key to create the Entra certificate."
  value       = aws_kms_key.outlook_signing.arn
}
