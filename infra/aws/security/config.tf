

data "aws_iam_policy_document" "config_recorder_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "config_recorder" {
  name               = "oconnordev-config-recorder"
  assume_role_policy = data.aws_iam_policy_document.config_recorder_assume_role.json
}

resource "aws_iam_role_policy_attachment" "config_recorder" {
  role       = aws_iam_role.config_recorder.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_config_configuration_recorder" "security" {
  # checkov:skip=CKV2_AWS_48:Deliberate. This check wants the recorder to record every possible resource type, which is exactly the configuration this design exists to avoid -- AWS Config is billed per configuration item recorded. The recording group lists the resource types this organization actually deploys.
  name     = "default"
  role_arn = aws_iam_role.config_recorder.arn

  recording_group {
    all_supported = false

    include_global_resource_types = false
    resource_types                = local.config_recorded_resource_types
  }
}

resource "aws_config_delivery_channel" "security" {
  name           = "default"
  s3_bucket_name = local.config_bucket_name

  depends_on = [
    aws_config_configuration_recorder.security,
    aws_s3_bucket_policy.config,
  ]
}

resource "aws_config_configuration_recorder_status" "security" {
  # checkov:skip=CKV2_AWS_45:Deliberate. Recording every supported resource type is the configuration that makes this account expensive -- AWS Config is billed per configuration item recorded. The recording group in this stack lists the resource types this organization actually deploys; recording all supported types is the opposite of the intent of this change.
  name       = aws_config_configuration_recorder.security.name
  is_enabled = true

  depends_on = [aws_config_delivery_channel.security]
}


data "aws_iam_policy_document" "config_aggregator_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["config.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "config_aggregator" {
  name               = "oconnordev-config-aggregator"
  assume_role_policy = data.aws_iam_policy_document.config_aggregator_assume_role.json
}

resource "aws_iam_role_policy_attachment" "config_aggregator" {
  role       = aws_iam_role.config_aggregator.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSConfigRoleForOrganizations"
}

resource "aws_config_configuration_aggregator" "organization" {
  name = "oconnordev-organization"

  organization_aggregation_source {
    all_regions = true
    role_arn    = aws_iam_role.config_aggregator.arn
  }

  depends_on = [aws_iam_role_policy_attachment.config_aggregator]
}
