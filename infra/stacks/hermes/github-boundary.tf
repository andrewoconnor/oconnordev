data "aws_region" "current" {}
data "aws_partition" "current" {}

data "aws_secretsmanager_secret" "github_machine_user_pat_existing" {
  name = "/hermes/github/machine-user-pat"
}

import {
  to = aws_secretsmanager_secret.github_machine_user_pat
  id = data.aws_secretsmanager_secret.github_machine_user_pat_existing.arn
}

resource "aws_secretsmanager_secret" "github_machine_user_pat" {
  name        = data.aws_secretsmanager_secret.github_machine_user_pat_existing.name
  description = data.aws_secretsmanager_secret.github_machine_user_pat_existing.description
  # Preserve an explicit customer-managed key. An empty metadata value means
  # Secrets Manager's default aws/secretsmanager KMS key, so leave this unset.
  kms_key_id = trimspace(data.aws_secretsmanager_secret.github_machine_user_pat_existing.kms_key_id) != "" ? data.aws_secretsmanager_secret.github_machine_user_pat_existing.kms_key_id : null

  lifecycle {
    prevent_destroy = true
  }
}

variable "hermes_github_allowed_repositories" {
  description = "AWS-side allowlist of repository names owned by andrewoconnor. Empty denies all access."
  type        = set(string)
  default     = ["oconnordev"]

  validation {
    condition = alltrue([
      for repository in var.hermes_github_allowed_repositories : can(regex("^[A-Za-z0-9_.-]{1,100}$", repository)) && !startswith(repository, ".") && !endswith(repository, ".git")
    ])
    error_message = "Allowed repository entries must be repository names only (no owner, slash, or URL)."
  }
}

variable "hermes_github_default_branches" {
  description = "Configured default branch for each allowlisted repository; writes and PR bases are constrained against these values."
  type        = map(string)
  default     = { oconnordev = "master" }

  validation {
    condition = alltrue([
      for repository in keys(var.hermes_github_default_branches) : contains(var.hermes_github_allowed_repositories, repository)
    ])
    error_message = "Default-branch map keys must be present in hermes_github_allowed_repositories."
  }

  validation {
    condition = alltrue([
      for repository in var.hermes_github_allowed_repositories : contains(keys(var.hermes_github_default_branches), repository)
    ])
    error_message = "Set a configured default branch for every allowlisted repository before enabling writes."
  }

  validation {
    condition = alltrue([
      for branch in values(var.hermes_github_default_branches) : can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$", branch)) && !strcontains(branch, "..") && !strcontains(branch, "//") && !endswith(branch, "/")
    ])
    error_message = "Default branch values must be valid, non-empty Git branch names."
  }
}

variable "hermes_github_machine_user_pat_json_key" {
  description = "JSON object key holding the GitHub PAT in the existing Secrets Manager secret. AgentCore EXTERNAL credential providers require SecretString to be a JSON object (for example, {\"api_key\":\"<PAT>\"}); plaintext SecretString is rejected. Terraform never reads or manages the value."
  type        = string
  default     = "api_key"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{1,64}$", var.hermes_github_machine_user_pat_json_key))
    error_message = "hermes_github_machine_user_pat_json_key must be a non-empty JSON key name."
  }
}

locals {
  hermes_gateway_name       = "hermes"
  hermes_policy_engine_name = "hermes_policy_engine"
  github_target_name        = "github"
  gateway_scope             = "hermes-mcp/invoke"
  github_tool_manifest      = jsondecode(file("${path.module}/adapter/github-mcp-tools.json"))
  github_native_tools       = toset(local.github_tool_manifest.tools)
  github_read_tools         = toset(["get_file_contents", "list_branches", "get_commit", "pull_request_read"])
  github_branch_tools       = toset(["create_branch", "push_files"])
  github_policy_tools       = setunion(local.github_read_tools, local.github_branch_tools, toset(["create_pull_request"]))
  hermes_cognito_domain     = "hermes-mcp-${data.aws_caller_identity.current.account_id}"
  cognito_issuer            = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.hermes.id}"
  cognito_token_url         = "https://${aws_cognito_user_pool_domain.hermes.domain}.auth.${data.aws_region.current.region}.amazoncognito.com/oauth2/token"
  github_cedar_repo_set     = jsonencode(sort(tolist(var.hermes_github_allowed_repositories)))

  github_branch_policy_matrix = {
    for pair in setproduct(var.hermes_github_allowed_repositories, local.github_branch_tools) : jsonencode(pair) => {
      repository     = pair[0]
      tool           = pair[1]
      default_branch = var.hermes_github_default_branches[pair[0]]
    }
  }
}

resource "aws_bedrockagentcore_api_key_credential_provider" "github" {
  name                  = "hermes-github-machine-user-pat"
  api_key_secret_source = "EXTERNAL"

  # Manually provision SecretString as a JSON object containing json_key. Do
  # not add aws_secretsmanager_secret_version: keep the PAT outside Terraform.
  api_key_secret_config {
    secret_id = aws_secretsmanager_secret.github_machine_user_pat.arn
    json_key  = var.hermes_github_machine_user_pat_json_key
  }
}

resource "aws_bedrockagentcore_policy_engine" "hermes" {
  name        = local.hermes_policy_engine_name
  description = "Default-deny Cedar guardrails for Hermes MCP targets and tools."
}

data "aws_iam_policy_document" "hermes_gateway_trust" {
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

resource "aws_iam_role" "hermes_gateway" {
  name               = "hermes-agentcore-gateway"
  assume_role_policy = data.aws_iam_policy_document.hermes_gateway_trust.json
}

resource "aws_cognito_user_pool" "hermes" {
  name = "hermes-mcp-m2m"
}

resource "aws_cognito_resource_server" "hermes" {
  user_pool_id = aws_cognito_user_pool.hermes.id
  identifier   = "hermes-mcp"
  name         = "Hermes MCP gateway"

  scope {
    scope_name        = "invoke"
    scope_description = "Invoke the shared Hermes MCP Gateway."
  }

  lifecycle {
    # Cognito permits both resource servers during the scope transition.
    # Keep the old scope until the client and Gateway use the new one.
    create_before_destroy = true
  }
}

resource "aws_cognito_user_pool_domain" "hermes" {
  domain       = local.hermes_cognito_domain
  user_pool_id = aws_cognito_user_pool.hermes.id
}

resource "aws_cognito_user_pool_client" "hermes" {
  name                                 = "hermes-mcp-local-adapter"
  user_pool_id                         = aws_cognito_user_pool.hermes.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = [aws_cognito_resource_server.hermes.scope_identifiers[0]]
  supported_identity_providers         = ["COGNITO"]
  access_token_validity                = 5

  token_validity_units {
    access_token = "minutes"
  }
}

data "aws_iam_policy_document" "hermes_gateway_core" {
  statement {
    sid     = "GetGatewayWorkloadAccessToken"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetWorkloadAccessToken"]
    resources = [
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "ReadGatewayPolicyEngine"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:GetPolicyEngine"]
    resources = [aws_bedrockagentcore_policy_engine.hermes.policy_engine_arn]
  }
}

data "aws_iam_policy_document" "github_target_credentials" {
  statement {
    sid       = "GetGitHubPATFromAgentCoreIdentity"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:GetResourceApiKey"]
    resources = [aws_bedrockagentcore_api_key_credential_provider.github.credential_provider_arn]
  }

  statement {
    sid       = "ReadOnlyGitHubPATSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.github_machine_user_pat.arn]
  }
}

data "aws_iam_policy_document" "hermes_gateway_policy_authorization" {
  statement {
    sid    = "AuthorizeGatewayActions"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:AuthorizeAction",
      "bedrock-agentcore:PartiallyAuthorizeActions",
    ]
    # Name-scoped ARN patterns avoid depending on generated resource IDs, so
    # Terraform can attach this policy before creating or updating the gateway.
    resources = [
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:policy-engine/${local.hermes_policy_engine_name}*",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:gateway/${local.hermes_gateway_name}*",
    ]
  }
}

resource "aws_iam_role_policy" "hermes_gateway_core" {
  name   = "hermes-agentcore-core"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.hermes_gateway_core.json
}

resource "aws_iam_role_policy" "github_target_credentials" {
  name   = "hermes-github-agentcore-credentials"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.github_target_credentials.json
}

resource "aws_iam_role_policy" "hermes_gateway_policy_authorization" {
  name   = "hermes-agentcore-policy"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.hermes_gateway_policy_authorization.json
}

resource "aws_bedrockagentcore_gateway" "hermes" {
  name            = local.hermes_gateway_name
  role_arn        = aws_iam_role.hermes_gateway.arn
  authorizer_type = "CUSTOM_JWT"
  protocol_type   = "MCP"

  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = "${local.cognito_issuer}/.well-known/openid-configuration"
      allowed_clients = [aws_cognito_user_pool_client.hermes.id]
      allowed_scopes  = [aws_cognito_resource_server.hermes.scope_identifiers[0]]

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

  policy_engine_configuration {
    arn  = aws_bedrockagentcore_policy_engine.hermes.policy_engine_arn
    mode = "ENFORCE"
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_gateway_target" "github" {
  name               = local.github_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Direct, dynamically listed target to GitHub's official hosted MCP server."

  credential_provider_configuration {
    api_key {
      provider_arn              = aws_bedrockagentcore_api_key_credential_provider.github.credential_provider_arn
      credential_location       = "HEADER"
      credential_parameter_name = "Authorization"
      credential_prefix         = "Bearer"
    }
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint = local.github_tool_manifest.hosted_endpoint
        # DEFAULT caches the MCP resource list at the control plane. An AgentCore
        # policy engine cannot enumerate a DYNAMIC target live, so creating the
        # Cedar policies fails while this target is dynamic ("its tools must be
        # listed live from the gateway and that listing failed"). The local
        # adapter still narrows tools/list to the seven GitHub-native tools in
        # the manifest, and Cedar default-deny still gates every other tool.
        listing_mode = "DEFAULT"
      }
    }
  }

  metadata_configuration {
    allowed_request_headers = ["x-mcp-tools"]
  }

  lifecycle {
    precondition {
      condition     = length(local.github_native_tools) == 7 && length(setsubtract(local.github_policy_tools, local.github_native_tools)) == 0
      error_message = "The GitHub MCP manifest must contain exactly the seven tool names covered by the Cedar policies."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.github_target_credentials,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "github_read" {
  for_each = length(var.hermes_github_allowed_repositories) == 0 ? toset([]) : local.github_read_tools

  name             = "HermesGitHubRead_${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Read-only ${each.key} is limited to the configured owner and repository allowlist."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal,
          action == AgentCore::Action::"${local.github_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          context.input has owner &&
          context.input.owner == "andrewoconnor" &&
          context.input has repo &&
          ${local.github_cedar_repo_set}.contains(context.input.repo)
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.github]
}

# JSON-schema arrays become Cedar Sets. The policy rejects an empty push_files
# batch; Cedar cannot quantify nested file records or enforce item/byte limits.
resource "aws_bedrockagentcore_policy" "github_branch_write" {
  for_each = local.github_branch_policy_matrix

  name             = "HermesGitHubWrite${replace(each.value.tool, "_", "")}${substr(sha256(each.value.repository), 0, 8)}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Allow ${each.value.tool} only on hermes/ feature branches in ${each.value.repository}."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal,
          action == AgentCore::Action::"${local.github_target_name}___${each.value.tool}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          context.input has owner &&
          context.input.owner == "andrewoconnor" &&
          context.input has repo &&
          context.input.repo == ${jsonencode(each.value.repository)} &&
          ${each.value.tool == "push_files" ? "context.input has files && !context.input.files.isEmpty() &&" : ""}
          context.input has branch &&
          context.input.branch like "hermes/*" &&
          context.input.branch != "hermes/" &&
          context.input.branch != ${jsonencode(each.value.default_branch)}
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.github]
}

resource "aws_bedrockagentcore_policy" "github_create_draft_pr" {
  for_each = {
    for repository, branch in var.hermes_github_default_branches : repository => branch
    if contains(var.hermes_github_allowed_repositories, repository)
  }

  name             = "HermesGitHubDraftPR${substr(sha256(each.key), 0, 12)}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Allow draft PR creation for ${each.key} only against its configured default branch."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal,
          action == AgentCore::Action::"${local.github_target_name}___create_pull_request",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          context.input has owner &&
          context.input.owner == "andrewoconnor" &&
          context.input has repo &&
          context.input.repo == ${jsonencode(each.key)} &&
          context.input has head &&
          ((context.input.head like "hermes/*" && context.input.head != "hermes/") ||
           (context.input.head like "andrewoconnor:hermes/*" && context.input.head != "andrewoconnor:hermes/")) &&
          context.input.head != ${jsonencode(each.value)} &&
          context.input has base &&
          context.input.base == ${jsonencode(each.value)} &&
          context.input has draft &&
          context.input.draft == true &&
          (!(context.input has maintainer_can_modify) || context.input.maintainer_can_modify == false) &&
          (!(context.input has reviewers) || context.input.reviewers.isEmpty())
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.github]
}

resource "aws_cloudwatch_metric_alarm" "gateway_user_errors" {
  alarm_name          = "hermes-gateway-user-errors"
  alarm_description   = "Repeated AgentCore Gateway 4xx responses, including rejected authentication or policy decisions."
  namespace           = "AWS/Bedrock-AgentCore"
  metric_name         = "UserErrors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    Resource = aws_bedrockagentcore_gateway.hermes.gateway_arn
  }
}

output "hermes_gateway_url" {
  description = "HTTPS MCP endpoint for the shared Hermes AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.hermes.gateway_url
}

output "hermes_gateway_origin_hostname" {
  description = "Gateway origin hostname for the production-account CloudFront reverse proxy."
  value       = split("/", trimprefix(aws_bedrockagentcore_gateway.hermes.gateway_url, "https://"))[0]
}

output "hermes_cognito_issuer" {
  description = "Cognito OIDC issuer used by the AgentCore JWT authorizer."
  value       = local.cognito_issuer
}

output "hermes_cognito_token_url" {
  description = "Cognito OAuth client-credentials token endpoint for the local adapter."
  value       = local.cognito_token_url
}

output "hermes_cognito_client_id" {
  description = "Non-secret Cognito M2M app client ID."
  value       = aws_cognito_user_pool_client.hermes.id
}

output "hermes_cognito_scope" {
  description = "The single OAuth scope accepted by the AgentCore Gateway."
  value       = local.gateway_scope
}

# Preserve legacy output names during the local adapter migration.
output "hermes_github_gateway_url" {
  description = "Deprecated compatibility alias for hermes_gateway_url."
  value       = aws_bedrockagentcore_gateway.hermes.gateway_url
}

output "hermes_github_cognito_issuer" {
  description = "Deprecated compatibility alias for hermes_cognito_issuer."
  value       = local.cognito_issuer
}

output "hermes_github_cognito_token_url" {
  description = "Deprecated compatibility alias for hermes_cognito_token_url."
  value       = local.cognito_token_url
}

output "hermes_github_cognito_client_id" {
  description = "Deprecated compatibility alias for hermes_cognito_client_id."
  value       = aws_cognito_user_pool_client.hermes.id
}

output "hermes_github_cognito_scope" {
  description = "Deprecated compatibility alias for hermes_cognito_scope."
  value       = local.gateway_scope
}
