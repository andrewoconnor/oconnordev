# ---------------------------------------------------------------------------
# Durable, organization-wide CloudTrail logging.
#
# The trail is created HERE, in the management account. That is a constraint
# rather than a preference: a delegated administrator can create an organization
# trail, but AWS anchors the resulting resource in the management account, and
# CloudTrail then refuses to operate on it with the delegated administrator's
# credentials. Terraform created it from the security account and the next
# refresh failed with exactly that error:
#
#   Account number does not match caller's account.
#
#   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-delegated-administrator.html
#   "The management account remains the owner of any CloudTrail organization
#    resources the delegated administrator creates."
#
# The ownership is therefore split, and deliberately so:
#
#   * the trail is created here, by the account that owns it
#   * the bucket, its policy and its lifecycle stay in the security account, in
#     infra/aws/security/audit-bucket-cloudtrail.tf
#   * trusted access for cloudtrail.amazonaws.com and the delegated
#     administrator registration for the security account stay here too,
#     declared in security-delegation.tf and identity-center.tf
#
# The security account remains the CloudTrail delegated administrator for
# operational administration. It is only Terraform's create path that moved.
#
# ---------------------------------------------------------------------------
# STATE MIGRATION -- READ BEFORE APPLYING
# ---------------------------------------------------------------------------
#
# The trail already exists. An earlier version of this change created it from
# the security account, it lives at
# arn:aws:cloudtrail:us-east-1:905418422177:trail/oconnordev-organization, and
# it is currently tracked in the SECURITY stack's state as
# aws_cloudtrail.organization. Deleting this file from that stack does not
# remove it from that state, so unless the state is fixed first the security
# stack will plan to DESTROY a trail it does not own, and CloudTrail will refuse
# with the same "Account number does not match caller's account" error that made
# the earlier apply fail. The security stack gates hermes and production, so
# that failure blocks the whole chain again.
#
# This stack cannot simply create it either: CreateTrail against a name that
# already exists fails. The trail has to be adopted, not recreated.
#
# So, before the two-step apply described in config.tf:
#
#   1. On the security stack, drop the trail from state:
#        terraform state rm aws_cloudtrail.organization
#   2. On this stack, adopt the existing trail (count-indexed address):
#        terraform import 'aws_cloudtrail.organization[0]' oconnordev-organization
#
# Step 2 needs the trail's name, not its ARN, and only works once
# enable_management_account_audit is true. After the import the plan is an
# in-place update: what changes is s3_key_prefix, from the "cloudtrail" prefix
# the earlier apply set to none.
# ---------------------------------------------------------------------------
#
# The two sides cannot reference each other across stacks: the trail names the
# security account's bucket as a literal, and the bucket policy names this
# trail's ARN as a literal. That is what keeps the Spacelift dependency
# direction general -> security intact -- closing the loop with a reverse
# dependency would be a cycle.
#
# Logs land at the root of oconnordev-cloudtrail, under an AWSLogs/<account-id>/
# layout with no key prefix, so the bucket policy names
# AWSLogs/<management-account-id>/* and AWSLogs/<organization-id>/* directly.
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

locals {
  cloudtrail_trail_name = "oconnordev-organization"

  # The bucket lives in the security account. It is a literal because this stack
  # is upstream of the security stack and cannot reference its resources; keep in
  # sync with local.cloudtrail_bucket_name in infra/aws/security/main.tf.
  cloudtrail_bucket_name = "oconnordev-cloudtrail"

  # This account IS the management account, so the trail ARN can be derived
  # rather than hard-coded here. The security stack carries the same ARN as a
  # literal in its bucket policy's aws:SourceArn condition; the two must match
  # exactly or CloudTrail's writes into that bucket are rejected.
  cloudtrail_trail_arn = "arn:${data.aws_partition.current.partition}:cloudtrail:us-east-1:${data.aws_caller_identity.current.account_id}:trail/${local.cloudtrail_trail_name}"
}

# ---------------------------------------------------------------------------
# The organization trail.
#
# Gated with the Config recorder behind var.enable_management_account_audit: the
# destination bucket lives in the security account, which applies after this
# stack, so on the first apply it does not exist yet. See the apply-order note at
# the top of config.tf.
#
# enable_log_file_validation turns on digest files so that a log file's integrity
# can be proven after the fact -- without it, tampering with the bucket is
# undetectable.
# ---------------------------------------------------------------------------

resource "aws_cloudtrail" "organization" {
  # checkov:skip=CKV_AWS_252:Deliberate. This design deliberately does not send CloudTrail to CloudWatch Logs; S3 is the durable destination and CloudWatch Logs would add ingestion and storage cost for a second copy nobody queries.
  # checkov:skip=CKV2_AWS_10:Deliberate. Same decision as CKV_AWS_252 -- no CloudWatch Logs integration, so there is no log group to embed.
  # checkov:skip=CKV_AWS_35:Deliberate. A CMK would add a customer-managed key plus per-request KMS charges and require kms:Decrypt/GenerateDataKey grants for CloudTrail in the bucket policy. Log files are encrypted with SSE-S3 (AES256); revisit if a CMK requirement ever appears.
  count = var.enable_management_account_audit ? 1 : 0

  name                          = local.cloudtrail_trail_name
  s3_bucket_name                = local.cloudtrail_bucket_name
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

  # Scoped to the Config bucket and to nothing else. That records who reads or
  # alters recorded configuration, and deliberately excludes the CloudTrail
  # bucket: logging object-level events on the tree CloudTrail itself writes
  # would have the trail logging its own writes.
  #
  # resources.ARN must be matched with starts_with, not equals. The value is an
  # object-key PREFIX (every object in the bucket), and equals would only ever
  # match an object whose key is exactly the bucket ARN, i.e. nothing. The prefix
  # is the bucket root rather than a sub-prefix because neither the trail nor any
  # Config delivery channel sets an s3_key_prefix any more.
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
        starts_with = ["arn:${data.aws_partition.current.partition}:s3:::${local.config_bucket_name}/"]
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Optional data events.
#
# Off by default. Flipping enable_config_data_events to true records object-level
# S3 operations on the Config bucket. Cost is $0.10 per 100,000 data events;
# Config delivery plus any human reads is on the order of a few thousand events
# per month across all four accounts, so roughly $0.01/month at the current size.
# It is kept as a separate switch so that the decision is a one-line change
# against a known estimate.
# ---------------------------------------------------------------------------

variable "enable_config_data_events" {
  description = "Record S3 object-level data events on the Config bucket. Off by default; see the cost note in cloudtrail.tf."
  type        = bool
  default     = false
}

output "cloudtrail_trail_arn" {
  description = "ARN of the organization trail. Carries the management account ID, because the management account owns the trail. Mirrored as a literal in the CloudTrail bucket policy's aws:SourceArn condition in the security stack."
  value       = local.cloudtrail_trail_arn
}

output "cloudtrail_organization_log_prefix" {
  description = "S3 key prefix under which each account's organization-trail logs are delivered."
  value       = "AWSLogs/${data.aws_organizations_organization.current.id}/"
}

output "cloudtrail_management_account_fallback_prefix" {
  description = "S3 key prefix CloudTrail falls back to if the organization trail is ever converted to a single-account trail for the management account."
  value       = "AWSLogs/${data.aws_caller_identity.current.account_id}/"
}

output "cloudtrail_organization_trail_created" {
  description = "Whether the organization trail exists. False until enable_management_account_audit is set to true."
  value       = var.enable_management_account_audit
}