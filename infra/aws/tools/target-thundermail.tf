locals {
  thundermail_manifest      = jsondecode(file("${local.adapter_root}/thundermail-mcp-tools.json"))
  thundermail_tools         = toset(["imap_list_mailboxes", "imap_search_messages", "imap_get_message", "caldav_list_events"])
  thundermail_action_prefix = "thundermail___"
}
resource "terraform_data" "thundermail_catalog" {
  triggers_replace = [sha256(jsonencode({
    manifest = local.thundermail_manifest
    runtime  = jsondecode(file("${path.module}/lambdas/thundermail_mcp/tool-schemas.json"))
    digest   = local.thundermail_image_digest
  }))]
}
resource "aws_bedrockagentcore_gateway_target" "thundermail" {
  name               = "thundermail"
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "One pinned owner Thundermail mailbox; three native Rust Lambda read tools."
  credential_provider_configuration {
    gateway_iam_role {}
  }
  target_configuration {
    mcp {
      lambda {
        lambda_arn = local.thundermail_function_arn
        tool_schema {
          # AWS 6.70 SchemaDefinition supports type/properties/required/description,
          # not additionalProperties, bounds, enum, default or nullable unions.
          # Runtime enforces full strict contract; adapter exposes owned schemas.
          dynamic "inline_payload" {
            for_each = { for tool in local.thundermail_manifest.toolSchemas : tool.name => tool }
            content {
              name        = inline_payload.key
              description = inline_payload.value.description
              input_schema {
                type = "object"
                dynamic "property" {
                  for_each = inline_payload.value.inputSchema.properties
                  content {
                    name        = property.key
                    type        = try(tostring(property.value.type), "string")
                    description = try(property.value.description, null)
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
    replace_triggered_by = [terraform_data.thundermail_catalog]
    precondition {
      condition     = toset(local.thundermail_manifest.tools) == local.thundermail_tools && length(local.thundermail_manifest.tools) == length(local.thundermail_tools) && local.thundermail_manifest.gateway_action_prefix == local.thundermail_action_prefix && local.thundermail_manifest.client_tool_prefix == "thundermail-" && toset([for t in local.thundermail_manifest.toolSchemas : t.name]) == local.thundermail_tools && length(local.thundermail_manifest.toolSchemas) == length(local.thundermail_tools) && alltrue([for t in local.thundermail_manifest.toolSchemas : t.inputSchema.additionalProperties == false])
      error_message = "Only the exact strict native read tools with owned namespaces are supported."
    }
    precondition {
      condition     = local.thundermail_manifest.toolSchemas == jsondecode(file("${path.module}/lambdas/thundermail_mcp/tool-schemas.json")).tools
      error_message = "Owned strict schemas must exactly match the reviewed Rust runtime contract."
    }
  }
  depends_on = [aws_lambda_function.thundermail, aws_iam_role_policy.thundermail_gateway_invoke, aws_iam_role_policy.hermes_gateway_policy_authorization]
}
resource "aws_bedrockagentcore_policy" "thundermail_read" {
  for_each         = local.thundermail_tools
  name             = "HermesThundermail${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Exact owner-only read action ${each.key}; runtime forbids account override and writes."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"
  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.thundermail_action_prefix}${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${aws_cognito_resource_server.hermes.scope_identifiers[0]}*"
        };
      CEDAR
    }
  }
  depends_on = [aws_bedrockagentcore_gateway_target.thundermail]
}
