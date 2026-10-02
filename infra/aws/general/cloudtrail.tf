
locals {
  cloudtrail_trail_name = "oconnordev-organization"

  cloudtrail_bucket_name = "oconnordev-cloudtrail"

  cloudtrail_trail_arn = "arn:${data.aws_partition.current.partition}:cloudtrail:us-east-1:${data.aws_caller_identity.current.account_id}:trail/${local.cloudtrail_trail_name}"
}


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


variable "enable_config_data_events" {
  description = "Record S3 object-level data events on the Config bucket. Off by default; see the cost note in cloudtrail.tf."
  type        = bool
  default     = false
}
