# ---------------------------------------------------------------------------
# The two central audit buckets, both owned by this account.
#
#   oconnordev-cloudtrail   organization CloudTrail logs and digest files
#   oconnordev-config       Config configuration history and snapshots, from
#                           GENERAL, PRODUCTION, HERMES and SECURITY
#
# Two buckets rather than two prefixes in one bucket: the two streams have
# different consumers, different retention questions and different lifecycle
# answers, and separating them keeps each bucket policy down to the statements
# that one service actually needs. Neither bucket grants this account's own
# principals read access in its policy -- the bucket lives in the account whose
# administrators read it, so same-account identity policy covers that (account
# administrators hold AdministratorAccess; the security gateway role holds
# ReadOnlyAccess). A bucket-policy read grant here would be a redundant second
# copy of a permission that already exists.
#
# Neither bucket has Object Lock. It was in the first cut of this change and has
# been dropped deliberately: GOVERNANCE mode does not stop an account
# administrator, who holds s3:BypassGovernanceRetention, and COMPLIANCE mode
# cannot be undone by anyone, which turns a retention setting into a permanent
# decision. Versioning plus the bucket-deletion deny cover the realistic failure
# modes at this size.
#
# The buckets live here rather than in the management account because this
# account is the organization's read vantage point, and because service control
# policies apply to a member account but not to the management account.
# ---------------------------------------------------------------------------

# Needed for the organization-trail write path in the CloudTrail bucket policy.
# A member account that is the CloudTrail delegated administrator can call
# ListAccounts, so this resolves without the management account's credentials.
data "aws_organizations_organization" "current" {}

locals {
  cloudtrail_key_prefix = "cloudtrail"
  config_key_prefix     = "config"

  # Every account that delivers into the Config bucket, and the recorder role
  # each one uses. The role name is fixed by the four config.tf files; it is
  # repeated rather than looked up because three of the four live in other
  # accounts.
  config_source_account_ids = [
    "905418422177", # GENERAL
    "767397796791", # PRODUCTION
    "421680664125", # HERMES
    "482921124454", # SECURITY, this account
  ]

  config_recorder_role_arns = [
    for account_id in local.config_source_account_ids :
    "arn:${data.aws_partition.current.partition}:iam::${account_id}:role/oconnordev-config-recorder"
  ]
}

# ---------------------------------------------------------------------------
# oconnordev-cloudtrail -- organization CloudTrail logs and digest files.
#
# CloudTrail writes here as a service principal from the management account,
# which owns the trail even though this account creates and manages it. The
# aws:SourceArn condition pins every write to that one trail, so no other trail
# in any account in this organization can write to this bucket.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "cloudtrail" {
  # checkov:skip=CKV_AWS_18:Access logging would need a second bucket plus a log-delivery policy and grant. Nothing consumes access logs for the audit bucket; read access is already limited to this account's own administrator and gateway roles by identity policy.
  # checkov:skip=CKV_AWS_144:Cross-region replication would need a replica bucket and a replication role in a second Region. The organization is entirely us-east-1, and replication would double the (already negligible) storage cost for no benefit at this size.
  # checkov:skip=CKV2_AWS_62:Event notifications need a consumer. Nothing subscribes to object-created events on the audit bucket.
  # checkov:skip=CKV_AWS_145:SSE-KMS would add a customer-managed key plus a per-request KMS charge and require kms:Decrypt/GenerateDataKey grants for CloudTrail in the bucket policy. Log files are encrypted with SSE-S3 (AES256). Revisit if a CMK requirement ever appears.
  bucket = local.cloudtrail_bucket_name
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  # Disables ACLs entirely. CloudTrail writes as a service principal, so under
  # BucketOwnerEnforced every object is owned by this account regardless of
  # which account's events it carries. CloudTrail passes
  # s3:x-amz-acl bucket-owner-full-control, which S3 accepts as a no-op under
  # this setting, and the bucket policy still conditions on that header.
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    # SSE-C would let a caller supply its own key, which CloudTrail does not do.
    blocked_encryption_types = ["SSE-C"]
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  # No storage-class transition rule. This bucket is on the order of megabytes,
  # so moving it to Glacier would save a fraction of a cent per month while
  # adding 90- and 180-day minimum-storage-duration charges and retrieval
  # complexity. Transitioning is a decision to make once the bucket is large
  # enough to matter, not before.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Versioning is on so a bad write to the audit log can be rolled back; this
  # keeps that from accumulating storage unbounded.
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# Three statements, which is the documented shape for an organization trail:
# an ACL check, the write path used if the trail is ever changed back to a
# single-account trail for the management account, and the organization write
# path.
#
#   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-create-and-update-an-organizational-trail-by-using-the-aws-cli.html
data "aws_iam_policy_document" "cloudtrail_bucket" {
  statement {
    sid    = "AWSCloudTrailAclCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_trail_arn]
    }
  }

  # Management-account fallback prefix. CloudTrail writes under the trail
  # owner's account ID if the trail is ever changed from an organization trail
  # to a trail for one account only; leaving this out means logging silently
  # stops the moment anyone makes that change.
  statement {
    sid    = "AWSCloudTrailWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail.arn}/${local.cloudtrail_key_prefix}/AWSLogs/${local.management_account_id}/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_trail_arn]
    }
  }

  # Organization write path. An organization trail delivers every account's logs
  # under the organization ID, so this is the path that carries all four
  # accounts' events.
  statement {
    sid    = "AWSCloudTrailOrganizationWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail.arn}/${local.cloudtrail_key_prefix}/AWSLogs/${data.aws_organizations_organization.current.id}/*"]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.cloudtrail_trail_arn]
    }
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.cloudtrail.arn,
      "${aws_s3_bucket.cloudtrail.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # Deletion protection. This denies DeleteBucket to every principal including
  # the account root, so an intentional teardown must remove this statement
  # first. That is the point: the audit bucket should not be destroyable by a
  # stray plan or a single mistaken console click.
  statement {
    sid    = "DenyBucketDeletion"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions   = ["s3:DeleteBucket"]
    resources = [aws_s3_bucket.cloudtrail.arn]
  }
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id
  policy = data.aws_iam_policy_document.cloudtrail_bucket.json

  depends_on = [
    aws_s3_bucket_public_access_block.cloudtrail,
    aws_s3_bucket_ownership_controls.cloudtrail,
    aws_s3_bucket_versioning.cloudtrail,
  ]
}

# ---------------------------------------------------------------------------
# oconnordev-config -- Config history and snapshots from all four accounts.
#
# Cross-account delivery is why this policy is longer than a same-account one
# would be. Config in the other three accounts writes here, which AWS documents
# as requiring both a service-principal grant and a grant to each recorder's IAM
# role:
#
#   https://docs.aws.amazon.com/config/latest/developerguide/s3-bucket-policy.html
#   "The IAM role you assign to the configuration recorder needs explicit
#    permission to perform the s3:ListBucket operation. This is because AWS
#    Config calls the Amazon S3 HeadBucket API with this IAM role to determine
#    the bucket location."
#   "The S3 bucket policy must include permissions for the IAM role assigned to
#    the configuration recorder."
#
# The recorder roles themselves need no extra inline permission: the managed
# policy they already carry, service-role/AWS_ConfigRole, grants s3:ListBucket on
# every resource. The delivery writes are made by the Config service principal,
# not by the recorder role.
#
# The delivery path is <prefix>/AWSLogs/<sourceAccountId>/Config/*, which is why
# the delivery resources below are built per source account rather than
# wildcarded.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "config" {
  # checkov:skip=CKV_AWS_18:Access logging would need a second bucket plus a log-delivery policy and grant. Nothing consumes access logs for the Config history bucket; Config delivers to it directly.
  # checkov:skip=CKV_AWS_144:Cross-region replication would need a replica bucket and a replication role in a second Region. Everything in this organization is us-east-1.
  # checkov:skip=CKV2_AWS_62:Event notifications need a consumer. Nothing subscribes to object-created events on the Config history bucket.
  # checkov:skip=CKV_AWS_145:SSE-KMS would add a customer-managed key plus a per-request KMS charge and require kms:Decrypt/GenerateDataKey grants for Config in the bucket policy. SSE-S3 (AES256) is what the per-account Config buckets used before this change.
  bucket = local.config_bucket_name
}

resource "aws_s3_bucket_public_access_block" "config" {
  bucket = aws_s3_bucket.config.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "config" {
  bucket = aws_s3_bucket.config.id

  # Disables ACLs entirely. Three other accounts write here, so object ownership
  # matters: under BucketOwnerEnforced every object is owned by this account
  # regardless of which account it came from. Config passes
  # s3:x-amz-acl bucket-owner-full-control, which S3 accepts as a no-op under
  # this setting, and the bucket policy still conditions on that header.
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "config" {
  bucket = aws_s3_bucket.config.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "config" {
  bucket = aws_s3_bucket.config.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    blocked_encryption_types = ["SSE-C"]
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "config" {
  bucket = aws_s3_bucket.config.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Versioning is on so a bad write to configuration history can be rolled back;
  # this keeps that from accumulating storage unbounded. Config rewrites the same
  # object paths as resources change, so noncurrent versions are the expected
  # case here rather than an exception.
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

data "aws_iam_policy_document" "config_bucket" {
  statement {
    sid    = "AWSConfigBucketPermissionsCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.config.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = local.config_source_account_ids
    }
  }

  statement {
    sid    = "AWSConfigBucketExistenceCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.config.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = local.config_source_account_ids
    }
  }

  # The cross-account HeadBucket check is made with each recorder's own IAM role,
  # not with the Config service principal, so the roles need their own grant.
  statement {
    sid    = "AWSConfigRecorderRoleExistenceCheck"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = local.config_recorder_role_arns
    }

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.config.arn]
  }

  statement {
    sid    = "AWSConfigBucketDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    actions = ["s3:PutObject"]
    resources = [
      for account_id in local.config_source_account_ids :
      "${aws_s3_bucket.config.arn}/${local.config_key_prefix}/AWSLogs/${account_id}/Config/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = local.config_source_account_ids
    }
  }

  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.config.arn,
      "${aws_s3_bucket.config.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid    = "DenyBucketDeletion"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions   = ["s3:DeleteBucket"]
    resources = [aws_s3_bucket.config.arn]
  }
}

resource "aws_s3_bucket_policy" "config" {
  bucket = aws_s3_bucket.config.id
  policy = data.aws_iam_policy_document.config_bucket.json

  depends_on = [
    aws_s3_bucket_public_access_block.config,
    aws_s3_bucket_ownership_controls.config,
    aws_s3_bucket_versioning.config,
  ]
}

output "cloudtrail_audit_bucket_name" {
  description = "Name of the organization CloudTrail log bucket."
  value       = aws_s3_bucket.cloudtrail.id
}

output "cloudtrail_audit_bucket_arn" {
  description = "ARN of the organization CloudTrail log bucket."
  value       = aws_s3_bucket.cloudtrail.arn
}

output "config_audit_bucket_name" {
  description = "Name of the central Config bucket. Delivery channels in GENERAL, PRODUCTION and HERMES point at this name."
  value       = aws_s3_bucket.config.id
}

output "config_audit_bucket_arn" {
  description = "ARN of the central Config bucket."
  value       = aws_s3_bucket.config.arn
}ers = [\"*\"]\n    }\n\n    actions   = [\"s3:DeleteBucket\"]\n    resources = [aws_s3_bucket.config.arn]\n  }\n}\n\nresource \"aws_s3_bucket_policy\" \"config\" {\n  bucket = aws_s3_bucket.config.id\n  policy = data.aws_iam_policy_document.config_bucket.json\n\n  depends_on = [\n    aws_s3_bucket_public_access_block.config,\n    aws_s3_bucket_ownership_controls.config,\n    aws_s3_bucket_versioning.config,\n  ]\n}\n\noutput \"cloudtrail_audit_bucket_name\" {\n  description = \"Name of the organization CloudTrail log bucket.\"\n  value       = aws_s3_bucket.cloudtrail.id\n}\n\noutput \"cloudtrail_audit_bucket_arn\" {\n  description = \"ARN of the organization CloudTrail log bucket.\"\n  value       = aws_s3_bucket.cloudtrail.arn\n}\n\noutput \"config_audit_bucket_name\" {\n  description = \"Name of the central Config bucket. Delivery channels in GENERAL, PRODUCTION and HERMES point at this name.\"\n  value       = aws_s3_bucket.config.id\n}\n\noutput \"config_audit_bucket_arn\" {\n  description = \"ARN of the central Config bucket.\"\n  value       = aws_s3_bucket.config.arn\n}\n"}]}}