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
# Logs are delivered to oconnordev-cloudtrail under the cloudtrail/ prefix. That
# bucket, its policy and its lifecycle live in audit-bucket-cloudtrail.tf.
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
#   * No data events by default. See var.enable_config_data_events for the
#     opt-in and its cost estimate.
#
# Cost shape for a small personal organization: the first trail in an account is
# free for management events, so the recurring cost here is only S3 storage and
# PUT requests. At a few MB per month that is a fraction of a cent.
# ---------------------------------------------------------------------------

data "aws_region" "current" {}

locals {
  cloudtrail_trail_name = "oconnordev-organization"

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
  # trail must be created after that policy exists, so referencing the resource
  # attribute here would make the dependency a cycle.
  cloudtrail_trail_arn = "arn:${data.aws_partition.current.partition}:cloudtrail:${data.aws_region.current.region}:${local.management_account_id}:trail/${local.cloudtrail_trail_name}"
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
  s3_key_prefix                 = local.cloudtrail_key_prefix
  is_organization_trail         = true
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  enable_logging                = true

  # Opt-in data events. When var.enable_config_data_events is false no
  # advanced_event_selector block is emitted at all, and the trail behaves as a
  # classic trail: every management event, in every Region, is recorded.
  #
  # The two blocks below are emitted together or not at all, and that is not
  # incidental: advanced event selectors REPLACE the classic event selectors
  # rather than adding to them. Configuring only a data-event selector would
  # leave the trail recording no management events at all.
  dynamic "advanced_event_selector" {
    for_each = var.enable_config_data_events ? [1] : []

    content {
      name = "Management events"

      field_selector {
        field  = "eventCategory"
        equals = ["Management"]
      }
    }
  }

  # Scoped to the config/ prefix of the Config bucket, and to nothing else. That
  # records who reads or alters recorded configuration, and deliberately excludes
  # the CloudTrail bucket: logging object-level events on the tree CloudTrail
  # itself writes would have the trail logging its own writes.
  #
  # resources.ARN must be matched with starts_with, not equals. The value is an
  # object-key PREFIX (everything under <bucket>/config/), and equals would only
  # ever match an object whose key is exactly that prefix, i.e. nothing.
  dynamic "advanced_event_selector" {
    for_each = var.enable_config_data_events ? [1] : []

    content {
      name = "Config history object-level events"

      field_selector {
        field  = "eventCategory"
        equals = ["Data"]
      }

      field_selector {
        field  = "resources.type"
        equals = ["AWS::S3::Object"]
      }

      field_selector {
        field       = "resources.ARN"
        starts_with = ["${aws_s3_bucket.config.arn}/${local.config_key_prefix}/"]
      }
    }
  }

  depends_on = [aws_s3_bucket_policy.cloudtrail]
}

# ---------------------------------------------------------------------------
# Optional data events.
#
# Off by default. Flipping enable_config_data_events to true records object-level
# S3 operations under the config/ prefix of the Config bucket. Cost is
# $0.10 per 100,000 data events; Config delivery plus any human reads is on the
# order of a few thousand events per month across all four accounts, so roughly
# $0.01/month at the current size. It is kept as a separate switch so that the
# decision is a one-line change against a known estimate.
# ---------------------------------------------------------------------------

variable "enable_config_data_events" {
  description = "Record S3 object-level data events under the config/ prefix of the Config bucket. Off by default; see the cost note in cloudtrail.tf."
  type        = bool
  default     = false
}

output "cloudtrail_trail_arn" {
  description = "ARN of the organization trail. Carries the management account ID, because the management account owns the trail. Also embedded in the CloudTrail bucket policy's aws:SourceArn condition."
  value       = local.cloudtrail_trail_arn
}

output "cloudtrail_organization_log_prefix" {
  description = "S3 key prefix under which each account's organization-trail logs are delivered."
  value       = "${local.cloudtrail_key_prefix}/AWSLogs/${data.aws_organizations_organization.current.id}/"
}

output "cloudtrail_management_account_fallback_prefix" {
  description = "S3 key prefix CloudTrail falls back to if the organization trail is ever converted to a single-account trail for the management account."
  value       = "${local.cloudtrail_key_prefix}/AWSLogs/${local.management_account_id}/"
}
