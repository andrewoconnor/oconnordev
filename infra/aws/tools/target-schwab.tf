locals {
  schwab_target_name = "schwab"
  schwab_manifest    = jsondecode(file("${local.adapter_root}/schwab-mcp-tools.json"))
  schwab_tools       = toset(local.schwab_manifest.tools)
  schwab_app_key     = "9UXqjUwlrByk8rd5iOqH7pvlxFYJtWJcTNzHzfy336iDP2nx"
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

resource "aws_bedrockagentcore_gateway_target" "schwab" {
  name               = local.schwab_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only Schwab Trader API accounts, positions and market data, with user-delegated OAuth through AgentCore Identity. No order endpoints."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.schwab.arn

        tool_schema {
          dynamic "inline_payload" {
            for_each = { for tool in local.schwab_tool_schemas : tool.name => tool }
            content {
              name        = inline_payload.key
              description = inline_payload.value.description
              input_schema {
                type = "object"
                dynamic "property" {
                  for_each = inline_payload.value.inputSchema.properties
                  content {
                    name        = property.key
                    type        = property.value.type
                    description = property.value.description
                    required    = contains(try(inline_payload.value.inputSchema.required, []), property.key)
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = toset([for tool in local.schwab_tool_schemas : tool.name]) == local.schwab_tools && length(local.schwab_tool_schemas) == length(local.schwab_tools) && alltrue([for tool in local.schwab_tool_schemas : (startswith(tool.path, "/trader/v1/accounts") || startswith(tool.path, "/marketdata/v1/")) && !strcontains(lower(tool.path), "order")])
      error_message = "The Schwab tool schemas must equal the adapter manifest and use only account and market data paths. Order endpoints must never be added."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.schwab_gateway_invoke,
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
