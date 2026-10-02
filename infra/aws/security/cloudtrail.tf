# ---------------------------------------------------------------------------
# Durable, organization-wide CloudTrail logging.
#
# The audit plane lives in this account, not in the management account. The
# management account keeps two things and nothing else: trusted access for
# cloudtrail.amazonaws.com, and the delegated-administrator registration that
# points at this account. Both are declared in
# infra/aws/general/security-delegation.tf and identity-center.tf, and this
# stack depends on that one, so they are in place before anything here runs.
#
# A CloudTrail delegated administrator is a member account that can perform the
# same administrative tasks in CloudTrail as the management account:
#
#   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-delegated-administrator.html
#   "A delegated administrator is a member account in an organization that can
#    perform the same administrative tasks (except as noted) in CloudTrail as
#    the management account."
#
# This is why the audit plane can be a member account at all. It also puts the
# log bucket inside the organization's own guardrails: service control policies
# do not restrict the management account, but they do apply here. That is the
# same reasoning as the Config aggregator and the Access Analyzer in this stack.
#
# What this adds:
#
#   * One organization trail covering every account in the organization and
#     every Region, created and managed from here.
#   * Management events only, delivered to a dedicated S3 bucket in this
#     account, with log-file integrity validation enabled.
#
# What this deliberately does NOT do:
#
#   * It does not replace or shorten CloudTrail Event History. Event History is
#     a separate, account-scoped, 90-day lookback that costs nothing and needs no
#     configuration; it keeps working exactly as it does today. This trail exists
#     because Event History is not durable, cannot be archived, cannot be read
#     from another account, and expires.
#   * No CloudWatch Logs delivery.
#   * No CloudTrail Lake event data stores (billed per GB ingested).
#   * No CloudTrail Insights (billed per 100,000 analyzed events).
#   * No data events. See var.enable_config_bucket_data_events for the opt-in.
#
# Cost shape for a small personal organization: the first trail in an account is
# free for management events, so the recurring cost here is only S3 storage and
# PUT requests. At a few MB per month that is a fraction of a cent.
# ---------------------------------------------------------------------------

# The organization ID is needed to build the log prefix. ListAccounts is
# callable from a member account that is the delegated administrator, so this
# data source resolves without the management account's credentials.
data "aws_organizations_organization" "current" {}

data "aws_region" "current" {}

locals {
  cloudtrail_bucket_name = "oconnordev-cloudtrail-${data.aws_caller_identity.current.account_id}"
  cloudtrail_trail_name  = "oconnordev-organization"

  # The management account, not this one. An organization trail created by a
  # delegated administrator is still OWNED by the management account:
  #
  #   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-delegated-administrator.html
  #   "The management account remains the owner of any CloudTrail organization
  #    resources the delegated administrator creates."
  #
  # The trail ARN therefore carries the management account ID, and the bucket
  # policy's aws:SourceArn condition must match it exactly. Using this account's
  # ID here would point the condition at a trail that does not exist, and
  # CloudTrail's writes would be rejected:
  #
  #   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/creating-an-organizational-trail-prepare.html
  #   "The trail ARN must use the account ID of the management account."
  management_account_id = "905418422177"

  # Built as a literal rather than read from aws_cloudtrail.organization.arn.
  # The bucket policy must name this ARN in its aws:SourceArn condition, and the
  # trail must be created after the policy exists, so referencing the resource
  # attribute here would make the dependency a cycle.
  cloudtrail_trail_arn = "arn:${data.aws_partition.current.partition}:cloudtrail:${data.aws_region.current.region}:${local.management_account_id}:trail/${local.cloudtrail_trail_name}"
}

# ---------------------------------------------------------------------------
# The central log bucket.
#
# Versioning is what makes an overwrite recoverable; Object Lock is what makes a
# delete recoverable. Both are on. Object Lock is GOVERNANCE mode, never
# COMPLIANCE: COMPLIANCE cannot be undone by anyone, including the account root,
# which turns a 90-day retention choice into a permanent one and blocks any
# future lifecycle or teardown decision.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "cloudtrail" {
  # checkov:skip=CKV_AWS_18:Access logging would need a second bucket plus a log-delivery policy and grant. Nothing consumes access logs for the audit bucket; read access is already limited to this account's own administrator and gateway roles by identity policy.
  # checkov:skip=CKV_AWS_144:Cross-region replication would need a replica bucket and a replication role in a second Region. The organization is entirely us-east-1, and replication would double the (already negligible) storage cost for no benefit at this size.
  # checkov:skip=CKV2_AWS_62:Event notifications need a consumer. Nothing subscribes to object-created events on the audit bucket.
  # checkov:skip=CKV_AWS_145:SSE-KMS would add a customer-managed key plus a per-request KMS charge and require kms:Decrypt/GenerateDataKey grants for CloudTrail in the bucket policy. Chosen SSE-S3 (AES256) matches the Config history bucket's existing decision in this stack. Revisit both together if a CMK requirement ever appears.
  bucket              = local.cloudtrail_bucket_name
  object_lock_enabled = true
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

  # Disables ACLs entirely. CloudTrail writes into this bucket on behalf of the
  # trail owner in the management account, so object ownership matters: under
  # BucketOwnerEnforced every object is owned by this account regardless of which
  # account the trail belongs to. CloudTrail's PutObject calls pass
  # s3:x-amz-acl bucket-owner-full-control, which S3 accepts as a no-op under
  # this setting, and the bucket policy still conditions on that header.
  rule {
    object_ownership = "BucketOwnerEnforced"
  }

  # Object Lock requires versioning; versioning is configured below and the
  # policy is applied after it.
  depends_on = [aws_s3_bucket.cloudtrail]
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
    # SSE-C would let a caller supply its own key, which CloudTrail never does.
    blocked_encryption_types = ["SSE-C"]
  }
}

resource "aws_s3_bucket_object_lock_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 90
    }
  }

  depends_on = [aws_s3_bucket_versioning.cloudtrail]
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  bucket = aws_s3_bucket.cloudtrail.id

  # No storage-class transition rule. The whole bucket is on the order of
  # megabytes, so moving it to Glacier would save a fraction of a cent per month
  # while adding 90- and 180-day minimum-storage-duration charges and retrieval
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

  # Superseded log versions are kept for 90 days. Note the interaction with
  # Object Lock: a noncurrent version is still locked for the remainder of its
  # own 90-day retention, so S3 may skip and retry an expiry that lands early.
  # That is expected and harmless at this size.
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# ---------------------------------------------------------------------------
# Bucket policy.
#
# The first three statements are the documented shape for an organization trail:
# an ACL check, the write path used if the trail is ever changed back to a
# single-account trail, and the organization write path. All three are
# conditioned on the exact trail ARN so that no other trail in any account can
# write here.
#
#   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-create-and-update-an-organizational-trail-by-using-the-aws-cli.html
#
# There is deliberately no statement granting this account's own principals
# access. The bucket now lives in the account whose administrators read it, so
# same-account identity policy is sufficient: the account administrators hold
# AdministratorAccess and the security gateway role holds ReadOnlyAccess. A
# bucket-policy grant would add a second, redundant way to reach the same data.
# ---------------------------------------------------------------------------

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

  # Management-account fallback prefix. CloudTrail writes under the trail owner's
  # account ID if the trail is ever changed from an organization trail to a trail
  # for one account only; leaving it out means logging silently stops the moment
  # anyone makes that change.
  statement {
    sid    = "AWSCloudTrailWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${local.management_account_id}/*"]

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

  # Organization log prefix. An organization trail delivers every account's logs
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
    resources = ["${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${data.aws_organizations_organization.current.id}/*"]

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
  # the account root, which means an intentional teardown must remove this
  # statement first. That is the point: the audit bucket should not be
  # destroyable by a stray plan or a single mistaken console click.
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
# The organization trail.
#
# This account can create it only because it is the registered CloudTrail
# delegated administrator for the organization. That registration lives in
# infra/aws/general/security-delegation.tf along with trusted access for
# cloudtrail.amazonaws.com, and the general stack must be applied first. There
# is no way to express that ordering in code across two stacks; it is carried by
# the Spacelift stack dependency from general to security.
#
# The management account remains the owner of this trail even though it is
# created here, so nothing in the management account needs to change if this
# account is ever replaced.
#
# enable_log_file_validation turns on digest files so that a log file's integrity
# can be proven after the fact -- without it, tampering with the bucket is
# undetectable.
# ---------------------------------------------------------------------------

resource "aws_cloudtrail" "organization" {
  # checkov:skip=CKV_AWS_252:Deliberate. This design deliberately does not send CloudTrail to CloudWatch Logs; S3 is the durable destination and CloudWatch Logs would add ingestion and storage cost for a second copy nobody queries.
  # checkov:skip=CKV2_AWS_10:Deliberate. Same decision as CKV_AWS_252 -- no CloudWatch Logs integration, so there is no log group to embed.
  # checkov:skip=CKV_AWS_35:Deliberate. A CMK would add a customer-managed key plus per-request KMS charges and require kms:Decrypt/GenerateDataKey grants for CloudTrail in the bucket policy. Log files are encrypted with SSE-S3 (AES256); revisit if a CMK requirement ever appears.
  name                          = local.cloudtrail_trail_name
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  is_organization_trail         = true
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  enable_logging                = true

  # Opt-in data events. When this list is empty no advanced_event_selector block
  # is emitted at all, and the trail behaves as a classic trail: every
  # management event, in every Region, is recorded.
  #
  # IMPORTANT, and the reason this is a single flag rather than two independent
  # switches: advanced event selectors REPLACE the classic event selectors
  # rather than adding to them. Configuring only a data-event selector would
  # leave the trail recording no management events at all. The two blocks below
  # are therefore emitted together or not at all.
  dynamic "advanced_event_selector" {
    for_each = var.enable_config_bucket_data_events ? [1] : []

    content {
      name = "Management events"

      field_selector {
        field  = "eventCategory"
        equals = ["Management"]
      }
    }
  }

  dynamic "advanced_event_selector" {
    for_each = var.enable_config_bucket_data_events ? [1] : []

    content {
      name = "Config history bucket object-level events"

      field_selector {
        field  = "eventCategory"
        equals = ["Data"]
      }

      field_selector {
        field  = "resources.type"
        equals = ["AWS::S3::Object"]
      }

      field_selector {
        field  = "resources.ARN"
        equals = local.config_bucket_object_arns
      }
    }
  }

  depends_on = [aws_s3_bucket_policy.cloudtrail]
}

# ---------------------------------------------------------------------------
# Optional data events.
#
# Off by default. Flipping enable_config_bucket_data_events to true records
# object-level S3 operations for the four Config history buckets, which is what
# answers "who read or altered the recorded configuration". Cost is
# $0.10 per 100,000 data events; Config delivery plus any human reads is on the
# order of a few thousand events per month across all four accounts, so roughly
# $0.01/month at the current size. It is kept as a separate switch so that the
# decision is a one-line change against a known estimate rather than something
# bundled into this change.
#
# The CloudTrail log bucket itself is deliberately NOT in this list: recording
# object-level events on the bucket CloudTrail writes to would have the trail
# logging its own writes.
# ---------------------------------------------------------------------------

variable "enable_config_bucket_data_events" {
  description = "Record S3 object-level data events for the Config history buckets. Off by default; see the cost note in cloudtrail.tf."
  type        = bool
  default     = false
}

locals {
  # The Config buckets follow the oconnordev-config-<account-id> convention in
  # every account's own stack. These IDs are already literals elsewhere in this
  # repository.
  config_bucket_account_ids = [
    "905418422177",
    "767397796791",
    "421680664125",
    "482921124454",
  ]

  # S3 object ARNs in advanced event selectors must be bucket-scoped and end
  # with a slash to match every object in the bucket.
  config_bucket_object_arns = [
    for account_id in local.config_bucket_account_ids :
    "arn:${data.aws_partition.current.partition}:s3:::oconnordev-config-${account_id}/"
  ]
}

output "cloudtrail_bucket_name" {
  description = "Name of the central CloudTrail log bucket. It lives in this account."
  value       = aws_s3_bucket.cloudtrail.id
}

output "cloudtrail_bucket_arn" {
  description = "ARN of the central CloudTrail log bucket. It lives in this account."
  value       = aws_s3_bucket.cloudtrail.arn
}

output "cloudtrail_trail_arn" {
  description = "ARN of the organization trail. Carries the management account ID, because the management account owns the trail. Also embedded in the bucket policy's aws:SourceArn condition."
  value       = local.cloudtrail_trail_arn
}

output "cloudtrail_organization_log_prefix" {
  description = "S3 key prefix under which each account's organization-trail logs are delivered."
  value       = "AWSLogs/${data.aws_organizations_organization.current.id}/"
}

output "cloudtrail_management_account_fallback_prefix" {
  description = "S3 key prefix CloudTrail falls back to if the organization trail is ever converted to a single-account trail for the management account."
  value       = "AWSLogs/${local.management_account_id}/"
}
