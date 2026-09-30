data "aws_region" "current" {}
data "aws_partition" "current" {}

data "aws_secretsmanager_secret" "github_app_private_key" {
  name = "/hermes/github/app-private-key"
}

variable "hermes_github_app_id" {
  description = "Non-secret GitHub App ID used to mint short-lived App JWTs. Leave empty only for a deny-all infrastructure plan; set before enabling the connector."
  type        = string
  default     = ""

  validation {
    condition     = var.hermes_github_app_id == "" || can(regex("^[0-9]+$", var.hermes_github_app_id))
    error_message = "hermes_github_app_id must be empty for a disabled plan or a numeric GitHub App ID."
  }
}

variable "hermes_github_installation_id" {
  description = "Non-secret GitHub App installation ID. Leave empty only for a deny-all infrastructure plan; set before enabling the connector."
  type        = string
  default     = ""

  validation {
    condition     = var.hermes_github_installation_id == "" || can(regex("^[0-9]+$", var.hermes_github_installation_id))
    error_message = "hermes_github_installation_id must be empty for a disabled plan or a numeric GitHub installation ID."
  }
}

variable "hermes_github_allowed_repositories" {
  description = "Trusted AWS-side allowlist of repository names owned by andrewoconnor. Empty denies all access."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for repository in var.hermes_github_allowed_repositories : can(regex("^[A-Za-z0-9_.-]{1,100}$", repository)) && !startswith(repository, ".") && !endswith(repository, ".git")
    ])
    error_message = "Allowed repository entries must be repository names only (no owner, slash, or URL)."
  }
}

locals {
  github_connector_name = "hermes-github-connector"
  github_gateway_name   = "hermes-github"
  github_target_name    = "github"
  github_scope          = "hermes-github/invoke"
  cognito_domain_prefix = "hermes-github-${data.aws_caller_identity.current.account_id}"
  cognito_issuer        = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.github.id}"
  cognito_token_url     = "https://${aws_cognito_user_pool_domain.github.domain}.auth.${data.aws_region.current.region}.amazoncognito.com/oauth2/token"
  github_log_group_arn  = "arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.github_connector_name}"
}

data "aws_iam_policy_document" "github_logs_kms" {
  statement {
    sid    = "EnableAccountIAMPermissions"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }

    actions   = ["kms:*"]
    resources = ["*"]
  }

  statement {
    sid    = "AllowCloudWatchLogsForConnectorLogGroup"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logs.${data.aws_region.current.region}.amazonaws.com"]
    }

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:Describe*",
    ]
    resources = ["*"]

    condition {
      test     = "ArnEquals"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = [local.github_log_group_arn]
    }
  }
}

resource "aws_kms_key" "github_logs" {
  description             = "Encrypt Hermes GitHub connector CloudWatch logs."
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.github_logs_kms.json
}

resource "aws_kms_alias" "github_logs" {
  name          = "alias/hermes-github-logs"
  target_key_id = aws_kms_key.github_logs.key_id
}

resource "aws_cloudwatch_log_group" "github_connector" {
  name              = "/aws/lambda/${local.github_connector_name}"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.github_logs.arn
}

data "aws_iam_policy_document" "github_connector_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "github_connector" {
  name               = "hermes-github-connector-lambda"
  assume_role_policy = data.aws_iam_policy_document.github_connector_trust.json
}

data "aws_iam_policy_document" "github_connector_runtime" {
  statement {
    sid       = "WriteOnlyToConnectorLogGroup"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:${aws_cloudwatch_log_group.github_connector.name}:*"]
  }

  statement {
    sid       = "ReadOnlyGitHubAppPrivateKey"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [data.aws_secretsmanager_secret.github_app_private_key.arn]
  }
}

resource "aws_iam_role_policy" "github_connector_runtime" {
  name   = "hermes-github-connector-runtime"
  role   = aws_iam_role.github_connector.id
  policy = data.aws_iam_policy_document.github_connector_runtime.json
}

data "archive_file" "github_connector" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/.terraform/hermes-github-connector.zip"
  excludes    = ["test/**", "package.json"]
}

resource "aws_s3_bucket" "github_lambda_artifacts" {
  bucket = "hermes-github-artifacts-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.region}"
}

resource "aws_s3_bucket_public_access_block" "github_lambda_artifacts" {
  bucket                  = aws_s3_bucket.github_lambda_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "github_lambda_artifacts" {
  bucket = aws_s3_bucket.github_lambda_artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "github_lambda_artifacts" {
  bucket = aws_s3_bucket.github_lambda_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "github_lambda_artifacts" {
  bucket = aws_s3_bucket.github_lambda_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_object" "github_connector_source" {
  bucket      = aws_s3_bucket.github_lambda_artifacts.id
  key         = "source/hermes-github-connector.zip"
  source      = data.archive_file.github_connector.output_path
  source_hash = data.archive_file.github_connector.output_base64sha256

  depends_on = [
    aws_s3_bucket_public_access_block.github_lambda_artifacts,
    aws_s3_bucket_ownership_controls.github_lambda_artifacts,
    aws_s3_bucket_versioning.github_lambda_artifacts,
    aws_s3_bucket_server_side_encryption_configuration.github_lambda_artifacts,
  ]
}

resource "aws_signer_signing_profile" "github_connector" {
  name        = "hermes_github_connector"
  platform_id = "AWSLambda-SHA384-ECDSA"

  signature_validity_period {
    value = 135
    type  = "MONTHS"
  }
}

resource "aws_lambda_code_signing_config" "github_connector" {
  description = "Require AWS Signer validation for the Hermes GitHub connector package."

  allowed_publishers {
    signing_profile_version_arns = [aws_signer_signing_profile.github_connector.version_arn]
  }

  policies {
    untrusted_artifact_on_deployment = "Enforce"
  }
}

resource "aws_signer_signing_job" "github_connector" {
  profile_name = aws_signer_signing_profile.github_connector.name

  source {
    s3 {
      bucket  = aws_s3_bucket.github_lambda_artifacts.id
      key     = aws_s3_object.github_connector_source.key
      version = aws_s3_object.github_connector_source.version_id
    }
  }

  destination {
    s3 {
      bucket = aws_s3_bucket.github_lambda_artifacts.id
      prefix = "signed/"
    }
  }
}

resource "aws_lambda_function" "github_connector" {
  function_name                  = local.github_connector_name
  description                    = "Allowlisted GitHub App change-proposal tools for Hermes AgentCore Gateway."
  role                           = aws_iam_role.github_connector.arn
  runtime                        = "nodejs26.x"
  handler                        = "index.handler"
  s3_bucket                      = aws_signer_signing_job.github_connector.signed_object[0].s3[0].bucket
  s3_key                         = aws_signer_signing_job.github_connector.signed_object[0].s3[0].key
  source_code_hash               = data.archive_file.github_connector.output_base64sha256
  code_signing_config_arn        = aws_lambda_code_signing_config.github_connector.arn
  timeout                        = 30
  memory_size                    = 256
  reserved_concurrent_executions = 5

  environment {
    variables = {
      GITHUB_APP_ID          = var.hermes_github_app_id
      GITHUB_INSTALLATION_ID = var.hermes_github_installation_id
      GITHUB_PRIVATE_KEY_ARN = data.aws_secretsmanager_secret.github_app_private_key.arn
      GITHUB_ALLOWED_REPOS  = jsonencode(sort(tolist(var.hermes_github_allowed_repositories)))
      GITHUB_OWNER           = "andrewoconnor"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.github_connector,
    aws_iam_role_policy.github_connector_runtime,
  ]
}

resource "aws_cloudwatch_log_metric_filter" "github_auth_failures" {
  name           = "hermes-github-auth-failures"
  log_group_name = aws_cloudwatch_log_group.github_connector.name
  pattern        = "{ $.category = \"github_authentication_failure\" }"

  metric_transformation {
    name          = "GitHubAuthenticationFailures"
    namespace     = "Hermes/GitHubConnector"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "github_connector_errors" {
  alarm_name          = "hermes-github-connector-errors"
  alarm_description   = "Elevated errors in the Hermes GitHub connector Lambda."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.github_connector.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "github_auth_failures" {
  alarm_name          = "hermes-github-auth-failures"
  alarm_description   = "Repeated GitHub App authentication failures in the connector."
  namespace           = "Hermes/GitHubConnector"
  metric_name         = aws_cloudwatch_log_metric_filter.github_auth_failures.metric_transformation[0].name
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "gateway_user_errors" {
  alarm_name          = "hermes-github-gateway-user-errors"
  alarm_description   = "Repeated AgentCore Gateway 4xx responses, including rejected authentication or requests."
  namespace           = "AWS/Bedrock-AgentCore"
  metric_name         = "UserErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Resource = aws_bedrockagentcore_gateway.github.gateway_arn
  }
}

resource "aws_cloudwatch_metric_alarm" "github_connector_throttles" {
  alarm_name          = "hermes-github-connector-throttles"
  alarm_description   = "The Hermes GitHub connector Lambda was throttled."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.github_connector.function_name
  }
}

data "aws_iam_policy_document" "gateway_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "github_gateway" {
  name               = "hermes-github-agentcore-gateway"
  assume_role_policy = data.aws_iam_policy_document.gateway_trust.json
}

data "aws_iam_policy_document" "gateway_invoke_connector" {
  statement {
    sid       = "InvokeOnlyGitHubConnector"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.github_connector.arn]
  }
}

resource "aws_iam_role_policy" "gateway_invoke_connector" {
  name   = "hermes-github-agentcore-invoke"
  role   = aws_iam_role.github_gateway.id
  policy = data.aws_iam_policy_document.gateway_invoke_connector.json
}

resource "aws_cognito_user_pool" "github" {
  name = "hermes-github-m2m"
}

resource "aws_cognito_resource_server" "github" {
  user_pool_id = aws_cognito_user_pool.github.id
  identifier   = "hermes-github"
  name         = "Hermes GitHub tools"

  scope {
    scope_name        = "invoke"
    scope_description = "Invoke the allowlisted Hermes GitHub tools."
  }
}

resource "aws_cognito_user_pool_domain" "github" {
  domain       = local.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.github.id
}

resource "aws_cognito_user_pool_client" "github" {
  name                                 = "hermes-github-local-adapter"
  user_pool_id                         = aws_cognito_user_pool.github.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                   = ["client_credentials"]
  allowed_oauth_scopes                  = [aws_cognito_resource_server.github.scope_identifiers[0]]
  supported_identity_providers          = ["COGNITO"]
  access_token_validity                 = 5

  token_validity_units {
    access_token = "minutes"
  }
}

resource "aws_bedrockagentcore_gateway" "github" {
  name            = local.github_gateway_name
  role_arn        = aws_iam_role.github_gateway.arn
  authorizer_type = "CUSTOM_JWT"
  protocol_type   = "MCP"

  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = "${local.cognito_issuer}/.well-known/openid-configuration"
      allowed_clients = [aws_cognito_user_pool_client.github.id]
      allowed_scopes  = [aws_cognito_resource_server.github.scope_identifiers[0]]

      custom_claim {
        inbound_token_claim_name       = "token_use"
        inbound_token_claim_value_type = "STRING"

        authorizing_claim_match_value {
          claim_match_operator = "EQUALS"

          claim_match_value {
            match_value_string = "access"
          }
        }
      }
    }
  }

  depends_on = [aws_iam_role_policy.gateway_invoke_connector]
}

resource "aws_bedrockagentcore_gateway_target" "github" {
  name               = local.github_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.github.gateway_id
  description        = "Five fixed, allowlisted GitHub change-proposal operations."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.github_connector.arn

        tool_schema {
          inline_payload {
            name        = "repository_info"
            description = "Read metadata and default-branch head for one allowlisted andrewoconnor repository."
            input_schema {
              type = "object"
              property {
                name        = "repository"
                type        = "string"
                description = "Repository name only; owner is fixed server-side."
                required    = true
              }
            }
          }

          inline_payload {
            name        = "read_files"
            description = "Read bounded text files from one allowlisted repository."
            input_schema {
              type = "object"
              property {
                name     = "repository"
                type     = "string"
                required = true
              }
              property {
                name        = "paths"
                type        = "array"
                description = "One to twenty-five safe repository-relative supported text-file paths."
                required    = true
                items {
                  type = "string"
                }
              }
              property {
                name = "ref"
                type = "string"
              }
            }
          }

          inline_payload {
            name        = "submit_change"
            description = "Create an idempotent feature branch and open a draft pull request against the configured default branch."
            input_schema {
              type = "object"
              property {
                name     = "repository"
                type     = "string"
                required = true
              }
              property {
                name        = "request_id"
                type        = "string"
                description = "Stable idempotency key."
                required    = true
              }
              property {
                name     = "expected_base_sha"
                type     = "string"
                required = true
              }
              property {
                name     = "title"
                type     = "string"
                required = true
              }
              property {
                name     = "body"
                type     = "string"
                required = true
              }
              property {
                name     = "files"
                type     = "array"
                required = true
                items {
                  type = "object"
                  property {
                    name     = "path"
                    type     = "string"
                    required = true
                  }
                  property {
                    name     = "content"
                    type     = "string"
                    required = true
                  }
                }
              }
            }
          }

          inline_payload {
            name        = "revise_change"
            description = "Revise files on an App-authored draft PR branch only when the expected head SHA matches."
            input_schema {
              type = "object"
              property {
                name     = "repository"
                type     = "string"
                required = true
              }
              property {
                name     = "pull_number"
                type     = "integer"
                required = true
              }
              property {
                name        = "request_id"
                type        = "string"
                description = "Stable idempotency key for this revision."
                required    = true
              }
              property {
                name     = "expected_head_sha"
                type     = "string"
                required = true
              }
              property {
                name     = "files"
                type     = "array"
                required = true
                items {
                  type = "object"
                  property {
                    name     = "path"
                    type     = "string"
                    required = true
                  }
                  property {
                    name     = "content"
                    type     = "string"
                    required = true
                  }
                }
              }
            }
          }

          inline_payload {
            name        = "change_status"
            description = "Read status of an App-authored Hermes draft pull request."
            input_schema {
              type = "object"
              property {
                name     = "repository"
                type     = "string"
                required = true
              }
              property {
                name     = "pull_number"
                type     = "integer"
                required = true
              }
            }
          }
        }
      }
    }
  }
}

output "hermes_github_gateway_url" {
  description = "Fixed HTTPS MCP endpoint for the local Hermes Cognito forwarding adapter."
  value       = aws_bedrockagentcore_gateway.github.gateway_url
}

output "hermes_github_cognito_issuer" {
  description = "Cognito OIDC issuer used by the AgentCore JWT authorizer."
  value       = local.cognito_issuer
}

output "hermes_github_cognito_token_url" {
  description = "Cognito OAuth client-credentials token endpoint for the local adapter."
  value       = local.cognito_token_url
}

output "hermes_github_cognito_client_id" {
  description = "Non-secret Cognito M2M app client ID."
  value       = aws_cognito_user_pool_client.github.id
}

output "hermes_github_cognito_scope" {
  description = "The single OAuth scope accepted by the AgentCore Gateway."
  value       = local.github_scope
}
