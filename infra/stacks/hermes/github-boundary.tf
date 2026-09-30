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
  # -1 leaves the function in the shared unreserved account concurrency pool.
  reserved_concurrent_executions = -1

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
  description        = "Six fixed, allowlisted GitHub change-proposal operations."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.github_connector.arn

        tool_schema {
          inline_payload {
            name        = "get_file_contents"
            description = "Upstream GitHub MCP get_file_contents. Owner is fixed to andrewoconnor; repo is checked against the AWS allowlist. Path/ref/sha and directory fields are bounded and validated server-side."
            input_schema {
              type = "object"
              property {
                name = "owner"
                type = "string"
                description = "Repository owner (username or organization); only andrewoconnor is accepted."
                required = true
              }
              property {
                name = "repo"
                type = "string"
                description = "Repository name in the AWS-side allowlist."
                required = true
              }
              property {
                name = "path"
                type = "string"
                description = "Path to file/directory; defaults to /."
              }
              property {
                name = "ref"
                type = "string"
                description = "Optional git ref, e.g. refs/heads/{branch}."
              }
              property {
                name = "sha"
                type = "string"
                description = "Optional commit SHA; takes precedence over ref."
              }
              property {
                name = "fields"
                type = "array"
                description = "Directory-entry fields: type, name, path, size, sha, url, git_url, html_url, download_url."
                items {
                  type = "string"
                }
              }
            }
          }

          inline_payload {
            name        = "list_branches"
            description = "Upstream GitHub MCP list_branches for an allowlisted repository."
            input_schema {
              type = "object"
              property {
                name = "owner"
                type = "string"
                description = "Only andrewoconnor is accepted."
                required = true
              }
              property {
                name = "repo"
                type = "string"
                description = "Repository name in the AWS-side allowlist."
                required = true
              }
              property {
                name = "page"
                type = "number"
                description = "Page number, minimum 1."
              }
              property {
                name = "perPage"
                type = "number"
                description = "Results per page, 1 to 100."
              }
            }
          }

          inline_payload {
            name        = "create_branch"
            description = "Upstream GitHub MCP create_branch. Creates only hermes/ feature branches based on the configured default branch."
            input_schema {
              type = "object"
              property {
                name = "owner"
                type = "string"
                description = "Only andrewoconnor is accepted."
                required = true
              }
              property {
                name = "repo"
                type = "string"
                description = "Repository name in the AWS-side allowlist."
                required = true
              }
              property {
                name = "branch"
                type = "string"
                description = "Must use the approved hermes/ feature-branch prefix."
                required = true
              }
              property {
                name = "from_branch"
                type = "string"
                description = "Source branch; if supplied it must equal the configured default branch."
              }
            }
          }

          inline_payload {
            name        = "push_files"
            description = "Upstream GitHub MCP push_files. Creates a single commit from bounded text files on an existing hermes/ branch; default-branch writes are rejected."
            input_schema {
              type = "object"
              property {
                name = "owner"
                type = "string"
                description = "Only andrewoconnor is accepted."
                required = true
              }
              property {
                name = "repo"
                type = "string"
                description = "Repository name in the AWS-side allowlist."
                required = true
              }
              property {
                name = "branch"
                type = "string"
                description = "Existing approved hermes/ feature branch; default branch is forbidden."
                required = true
              }
              property {
                name = "files"
                type = "array"
                description = "One to 25 safe text files, with per-file and total byte limits."
                required = true
                items {
                  type = "object"
                  property {
                    name = "path"
                    type = "string"
                    description = "Safe repository-relative path."
                    required = true
                  }
                  property {
                    name = "content"
                    type = "string"
                    description = "Text content; binary/NUL content is rejected."
                    required = true
                  }
                }
              }
              property {
                name = "message"
                type = "string"
                description = "Commit message."
                required = true
              }
            }
          }

          inline_payload {
            name        = "create_pull_request"
            description = "Upstream GitHub MCP create_pull_request. Server requires draft=true, head under hermes/, base equal to the configured default branch, no reviewers, and no maintainer edit delegation."
            input_schema {
              type = "object"
              property {
                name = "owner"
                type = "string"
                description = "Only andrewoconnor is accepted."
                required = true
              }
              property {
                name = "repo"
                type = "string"
                description = "Repository name in the AWS-side allowlist."
                required = true
              }
              property {
                name = "title"
                type = "string"
                description = "PR title."
                required = true
              }
              property {
                name = "body"
                type = "string"
                description = "PR description."
              }
              property {
                name = "head"
                type = "string"
                description = "Must be an existing hermes/ feature branch in this repository."
                required = true
              }
              property {
                name = "base"
                type = "string"
                description = "Must equal the repository configured default branch."
                required = true
              }
              property {
                name = "draft"
                type = "boolean"
                description = "Must be explicitly true; non-draft PRs are rejected."
              }
              property {
                name = "maintainer_can_modify"
                type = "boolean"
                description = "True is rejected by server policy."
              }
              property {
                name = "reviewers"
                type = "array"
                description = "Non-empty reviewer requests are rejected by server policy."
                items {
                  type = "string"
                }
              }
            }
          }

          inline_payload {
            name        = "pull_request_read"
            description = "Upstream GitHub MCP pull_request_read. Official methods are get, get_diff, get_status, get_files, get_commits, get_review_comments, get_reviews, get_comments, get_check_runs; this boundary permits get, get_diff, get_status, get_files, get_commits, and get_check_runs only."
            input_schema {
              type = "object"
              property {
                name = "method"
                type = "string"
                description = "Supported: get, get_diff, get_status, get_files, get_commits, get_check_runs. Other upstream methods are rejected."
                required = true
              }
              property {
                name = "owner"
                type = "string"
                description = "Only andrewoconnor is accepted."
                required = true
              }
              property {
                name = "repo"
                type = "string"
                description = "Repository name in the AWS-side allowlist."
                required = true
              }
              property {
                name = "pullNumber"
                type = "number"
                description = "Pull request number."
                required = true
              }
              property {
                name = "page"
                type = "number"
                description = "Page number, minimum 1."
              }
              property {
                name = "perPage"
                type = "number"
                description = "Results per page, 1 to 100."
              }
              property {
                name = "after"
                type = "string"
                description = "Upstream review-comment cursor; not accepted by this boundary."
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
