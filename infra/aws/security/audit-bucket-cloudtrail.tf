# ---------------------------------------------------------------------------
# oconnordev-cloudtrail -- the organization CloudTrail log bucket.
#
# CloudTrail writes here as a service principal from the management account,
# which owns the trail even though this account creates and manages it. The
# aws:SourceArn condition pins every write to that one trail, so no other trail
# in any account in this organization can write to this bucket.
#
# This bucket grants this account's own principals no read access in its policy.
# The bucket lives in the account whose administrators read it, so same-account
# identity policy covers that: account administrators hold AdministratorAccess
# and the security gateway role holds ReadOnlyAccess. A bucket-policy read grant
# would be a redundant second copy of a permission that already exists.
#
# No Object Lock. It was in the first cut of this change and has been dropped
# deliberately: GOVERNANCE mode does not stop an account administrator, who
# holds s3:BypassGovernanceRetention, and COMPLIANCE mode cannot be undone by
# anyone, which turns a retention setting into a permanent decision. Versioning
# plus the bucket-deletion deny cover the realistic failure modes at this size.
#
# The bucket lives here rather than in the management account because this
# account is the organization's read vantage point, and because service control
# policies apply to a member account but not to the management account.
# ---------------------------------------------------------------------------

# Needed for the organization-trail write path below. A member account that is
# the CloudTrail delegated administrator can call ListAccounts, so this resolves
# without the management account's credentials.
data "aws_organizations_organization" "current" {}

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

output "cloudtrail_audit_bucket_name" {
  description = "Name of the organization CloudTrail log bucket."
  value       = aws_s3_bucket.cloudtrail.id
}

output "cloudtrail_audit_bucket_arn" {
  description = "ARN of the organization CloudTrail log bucket."
  value       = aws_s3_bucket.cloudtrail.arn
}
