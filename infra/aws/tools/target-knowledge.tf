locals {
  knowledge_target_name   = "knowledge"
  knowledge_tool_manifest = jsondecode(file("${path.module}/knowledge-mcp-tools.json"))
  knowledge_endpoint      = local.knowledge_tool_manifest.endpoint
  knowledge_native_tools  = toset(local.knowledge_tool_manifest.tools)
  knowledge_read_only_tools = toset([
    "aws___get_regional_availability",
    "aws___list_regions",
    "aws___read_documentation",
    "aws___retrieve_skill",
    "aws___search_documentation",
  ])
  knowledge_required_scope = aws_cognito_resource_server.hermes.scope_identifiers[0]
}

# The public endpoint accepted MCP initialize/tools/list and a read-only list_regions call without credentials. Keep the exact current catalog pinned: an upstream tool addition must be reviewed before it can receive a Cedar permit.
resource "aws_bedrockagentcore_gateway_target" "knowledge" {
  name               = local.knowledge_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only AWS documentation, skills, and regional availability through AWS Knowledge MCP."

  target_configuration {
    mcp {
      mcp_server {
        endpoint     = local.knowledge_endpoint
        listing_mode = "DEFAULT"
      }
    }
  }

  lifecycle {
    precondition {
      condition = (
        length(setsubtract(local.knowledge_native_tools, local.knowledge_read_only_tools)) == 0 &&
        length(setsubtract(local.knowledge_read_only_tools, local.knowledge_native_tools)) == 0
      )
      error_message = "The AWS Knowledge MCP manifest must include exactly the complete read-only endpoint catalog."
    }

    precondition {
      condition     = local.knowledge_endpoint == "https://knowledge-mcp.global.api.aws"
      error_message = "The AWS Knowledge MCP target endpoint must remain pinned to the public read-only AWS endpoint."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "knowledge_tool" {
  for_each = local.knowledge_native_tools

  name             = "HermesKnowledge${replace(each.key, "_", "")}" 
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only AWS Knowledge MCP tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.knowledge_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${local.knowledge_required_scope}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.knowledge]
}
