locals {
  schwab_target_name = "schwab"
  schwab_manifest    = jsondecode(file("${local.adapter_root}/schwab-mcp-tools.json"))
  schwab_tools       = toset(local.schwab_manifest.tools)
  schwab_operations  = flatten([for path in values(local.schwab_openapi.paths) : [for method, operation in path : { method = method, id = operation.operationId }]])
  schwab_scopes      = ["api", "offline_access"]
  schwab_app_key     = "pending-schwab-app-key"
  schwab_secret_arns = compact([
    data.aws_secretsmanager_secret.schwab_oauth_client.arn,
    try(aws_bedrockagentcore_oauth2_credential_provider.schwab.client_secret_arn[0].secret_arn, ""),
  ])
}

data "aws_secretsmanager_secret" "schwab_oauth_client" {
  name = "/hermes/schwab/oauth-client-secret"
}

resource "aws_bedrockagentcore_oauth2_credential_provider" "schwab" {
  name                       = "hermes-schwab"
  credential_provider_vendor = "CustomOauth2"

  oauth2_provider_config {
    custom_oauth2_provider_config {
      client_id                    = local.schwab_app_key
      client_authentication_method = "CLIENT_SECRET_BASIC"
      client_secret_source         = "EXTERNAL"

      client_secret_config {
        secret_id = data.aws_secretsmanager_secret.schwab_oauth_client.arn
        json_key  = "client_secret"
      }

      oauth_discovery {
        authorization_server_metadata {
          issuer                 = "https://api.schwabapi.com"
          authorization_endpoint = "https://api.schwabapi.com/v1/oauth/authorize"
          token_endpoint         = "https://api.schwabapi.com/v1/oauth/token"
          response_types         = ["code"]
        }
      }
    }
  }
}

data "aws_iam_policy_document" "schwab_target_credentials" {
  statement {
    sid     = "GetSchwabTokenFromAgentCoreIdentity"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetResourceOauth2Token"]

    resources = [
      aws_bedrockagentcore_oauth2_credential_provider.schwab.credential_provider_arn,
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:token-vault/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "ReadSchwabOauthClientSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = local.schwab_secret_arns
  }
}

resource "aws_iam_role_policy" "schwab_target_credentials" {
  name   = "hermes-schwab-agentcore-credentials"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.schwab_target_credentials.json
}

resource "aws_bedrockagentcore_gateway_target" "schwab" {
  name               = local.schwab_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only Schwab Trader API accounts, positions and market data, with user-delegated OAuth through AgentCore Identity. No order endpoints."

  credential_provider_configuration {
    oauth {
      provider_arn       = aws_bedrockagentcore_oauth2_credential_provider.schwab.credential_provider_arn
      scopes             = local.schwab_scopes
      grant_type         = "AUTHORIZATION_CODE"
      default_return_url = local.oauth_callback_return_url
    }
  }

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = jsonencode(local.schwab_openapi)
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = alltrue([for operation in local.schwab_operations : operation.method == "get"]) && toset([for operation in local.schwab_operations : operation.id]) == local.schwab_tools && length(local.schwab_operations) == length(local.schwab_tools)
      error_message = "The Schwab OpenAPI spec must contain only GET operations, and its operation IDs must equal the adapter manifest. Order endpoints must never be added."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.schwab_target_credentials,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "schwab_read" {
  for_each = local.schwab_tools

  name             = "HermesSchwab${each.key}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only Schwab tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.schwab_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${aws_cognito_resource_server.hermes.scope_identifiers[0]}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.schwab]
}

output "schwab_oauth_callback_url" {
  description = "Register this exact URL as the Schwab app's callback URL."
  value       = aws_bedrockagentcore_oauth2_credential_provider.schwab.callback_url
}
