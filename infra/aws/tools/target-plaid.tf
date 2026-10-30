locals {
  plaid_target_name = "plaid"
  plaid_manifest    = jsondecode(file("${local.adapter_root}/plaid-mcp-tools.json"))
  plaid_tools       = toset(local.plaid_manifest.tools)
  plaid_read_endpoints = {
    getAccounts              = "/accounts/get"
    getTransactions          = "/transactions/get"
    getItemStatus            = "/item/get"
    getRecurringTransactions = "/transactions/recurring/get"
    getLiabilities           = "/liabilities/get"
    getHoldings              = "/investments/holdings/get"
  }
}

resource "aws_bedrockagentcore_gateway_target" "plaid" {
  name               = local.plaid_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only existing Plaid Items via six fixed production POST endpoints and local discovery; no consent or mutation tools."

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.plaid.arn

        tool_schema {
          dynamic "inline_payload" {
            for_each = { for tool in local.plaid_tool_schemas : tool.name => tool }
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
      condition     = toset([for tool in local.plaid_tool_schemas : tool.name]) == local.plaid_tools && length(local.plaid_tool_schemas) == length(local.plaid_tools) && local.plaid_tools == setunion(toset(["listItems"]), toset(keys(local.plaid_read_endpoints)))
      error_message = "Plaid native schemas and adapter manifest must equal local discovery and the fixed read endpoint catalog."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.plaid_gateway_invoke,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "plaid_read" {
  for_each = local.plaid_tools

  name             = "HermesPlaid${each.key}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only Plaid tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.plaid_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${aws_cognito_resource_server.hermes.scope_identifiers[0]}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.plaid]
}
