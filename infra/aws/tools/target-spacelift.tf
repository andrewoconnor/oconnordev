variable "hermes_spacelift_mcp_endpoint" {
  description = "Spacelift's official hosted MCP endpoint, pinned to the narrowed lookup-only tool set. The tools query parameter is the narrowing mechanism for API-key callers; without it the upstream also advertises mutate and intent, because the tool list describes the server's surface rather than the caller's permission."
  type        = string
  default     = "https://andrewoconnor.app.spacelift.io/mcp?tools=query,provider"

  validation {
    condition     = can(regex("^https://[a-z0-9-]+\\.app\\.spacelift\\.io/mcp\\?tools=query,provider$", var.hermes_spacelift_mcp_endpoint))
    error_message = "hermes_spacelift_mcp_endpoint must be an https Spacelift hosted MCP endpoint pinned to ?tools=query,provider. Any other tool set exposes the upstream's mutate or intent tools through the gateway."
  }
}

variable "hermes_spacelift_api_key_secret_name" {
  description = "Name of the existing Secrets Manager secret holding the read-only Spacelift API key. Only the rotation function may read it; the gateway execution role is explicitly denied it by hermes-agentcore-readonly-guardrails."
  type        = string
  default     = "/hermes/spacelift/api-key"

  validation {
    condition     = can(regex("^/[A-Za-z0-9/_+=.@-]{1,500}$", var.hermes_spacelift_api_key_secret_name))
    error_message = "hermes_spacelift_api_key_secret_name must be an absolute Secrets Manager secret name beginning with a slash."
  }
}

variable "hermes_spacelift_session_token_secret_name" {
  description = "Name of the secret the rotation function writes and the AgentCore credential provider reads. Deliberately separate from the long-lived API key so no principal holds both."
  type        = string
  default     = "/hermes/spacelift/session-token"

  validation {
    condition     = can(regex("^/[A-Za-z0-9/_+=.@-]{1,500}$", var.hermes_spacelift_session_token_secret_name))
    error_message = "hermes_spacelift_session_token_secret_name must be an absolute Secrets Manager secret name beginning with a slash."
  }
}

variable "hermes_spacelift_session_token_json_key" {
  description = "JSON object key holding the session JWT. AgentCore EXTERNAL credential providers require SecretString to be a JSON object, for example {\"token\":\"<JWT>\"}; plaintext SecretString is rejected."
  type        = string
  default     = "token"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{1,64}$", var.hermes_spacelift_session_token_json_key))
    error_message = "hermes_spacelift_session_token_json_key must be a non-empty JSON key name."
  }
}

locals {
  spacelift_target_name    = "spacelift"
  spacelift_tool_manifest  = jsondecode(file("${local.adapter_root}/spacelift-mcp-tools.json"))
  spacelift_native_tools   = toset(local.spacelift_tool_manifest.tools)
  spacelift_required_scope = aws_cognito_resource_server.hermes.scope_identifiers[0]
}

data "aws_secretsmanager_secret" "spacelift_api_key" {
  name = var.hermes_spacelift_api_key_secret_name
}

resource "aws_secretsmanager_secret" "spacelift_session_token" {
  # checkov:skip=CKV_AWS_149:Encrypted with the account's AWS-managed secrets key. A customer-managed key would need a key policy granting both the gateway execution role and the rotation function, and a key policy wrong in either direction fails the credential read at request time rather than loudly at apply.
  # checkov:skip=CKV2_AWS_57:Rotation is already implemented, just not through Secrets Manager's native rotation configuration. aws_lambda_function.spacelift_rotation runs on aws_cloudwatch_event_rule.spacelift_rotation and re-mints the session JWT from the read-only API key before its 10-hour window closes; aws_cloudwatch_metric_alarm.spacelift_session_token_stale alarms when the stored token ages out. Attaching a native rotation Lambda would add a second, competing rotator for the same value.
  name        = var.hermes_spacelift_session_token_secret_name
  description = "Short-lived Spacelift session JWT minted from the read-only API key. Read by the AgentCore gateway execution role, written only by the rotation function."
}

resource "aws_bedrockagentcore_api_key_credential_provider" "spacelift" {
  name                  = "hermes-spacelift-session-token"
  api_key_secret_source = "EXTERNAL"

  api_key_secret_config {
    secret_id = aws_secretsmanager_secret.spacelift_session_token.arn
    json_key  = var.hermes_spacelift_session_token_json_key
  }

  depends_on = [aws_lambda_invocation.spacelift_session_token_seed]
}

data "aws_iam_policy_document" "spacelift_target_credentials" {
  statement {
    sid     = "GetSpaceliftSessionTokenFromAgentCoreIdentity"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetResourceApiKey"]

    resources = [
      aws_bedrockagentcore_api_key_credential_provider.spacelift.credential_provider_arn,
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:token-vault/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "ReadOnlySpaceliftSessionTokenSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.spacelift_session_token.arn]
  }
}

resource "aws_iam_role_policy" "spacelift_target_credentials" {
  name   = "hermes-spacelift-agentcore-credentials"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.spacelift_target_credentials.json
}

resource "aws_bedrockagentcore_gateway_target" "spacelift" {
  name               = local.spacelift_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only Spacelift access through Spacelift's official hosted MCP server, narrowed to the lookup tools discover, provider and query."

  credential_provider_configuration {
    api_key {
      provider_arn              = aws_bedrockagentcore_api_key_credential_provider.spacelift.credential_provider_arn
      credential_location       = "HEADER"
      credential_parameter_name = "Authorization"
      credential_prefix         = "Bearer"
    }
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint     = var.hermes_spacelift_mcp_endpoint
        listing_mode = "DEFAULT"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = length(setsubtract(local.spacelift_native_tools, toset(["discover", "provider", "query"]))) == 0
      error_message = "The Spacelift manifest must contain only the read-only lookup tools discover, provider and query. mutate and intent must never be added: the upstream advertises both to a reader-scoped key, so the manifest is a load-bearing part of the read-only boundary."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.spacelift_target_credentials,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "spacelift_tool" {
  for_each = local.spacelift_native_tools

  name             = "HermesSpacelift${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only Spacelift MCP tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.spacelift_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${local.spacelift_required_scope}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.spacelift]
}
