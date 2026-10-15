locals {
  microsoft365_manifest        = jsondecode(file("${local.adapter_root}/microsoft365-mcp-tools.json"))
  microsoft365_runtime_catalog = jsondecode(file("${local.repo_root}/infra/tools/lambdas/microsoft365_mcp/tools-manifest.json"))
  microsoft365_tools           = toset(local.microsoft365_manifest.tools)
  microsoft365_action_prefix   = "microsoft365___"
}

resource "terraform_data" "microsoft365_catalog" {
  count = var.microsoft365_runtime_enabled ? 1 : 0
  triggers_replace = [sha256(jsonencode({
    manifest        = local.microsoft365_manifest
    runtime_catalog = local.microsoft365_runtime_catalog
    image_digest    = var.microsoft365_image_digest
  }))]
}

resource "aws_bedrockagentcore_gateway_target" "microsoft365" {
  count              = var.microsoft365_runtime_enabled ? 1 : 0
  name               = "microsoft365"
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "One pinned personal consumer mailbox, five read-only tools, IAM-authenticated MCP HTTP on Lambda Web Adapter."
  credential_provider_configuration {
    gateway_iam_role {
      service = "lambda"
      region  = "us-east-1"
    }
  }
  target_configuration {
    mcp {
      mcp_server {
        endpoint     = "${aws_lambda_function_url.microsoft365[0].function_url}mcp"
        listing_mode = "DEFAULT"
      }
    }
  }
  lifecycle {
    replace_triggered_by = [terraform_data.microsoft365_catalog[0]]
    precondition {
      condition     = toset([for tool in local.microsoft365_runtime_catalog : tool.name]) == local.microsoft365_tools && length(local.microsoft365_runtime_catalog) == 5 && alltrue([for tool in local.microsoft365_runtime_catalog : tool.inputSchema.additionalProperties == false])
      error_message = "Runtime strict schema artifact must match the manifest's exact five tools with unknown properties forbidden."
    }
    precondition {
      condition     = local.microsoft365_tools == toset(["get-mail-message", "list-mail-messages", "list-mail-folders", "list-mail-child-folders", "list-mail-folder-messages"]) && length(local.microsoft365_manifest.tools) == 5 && local.microsoft365_manifest.gateway_action_prefix == local.microsoft365_action_prefix
      error_message = "The Microsoft365 catalog must contain exactly the investigated five mail tools with the microsoft365___ wire prefix."
    }
  }
  depends_on = [aws_iam_role_policy.microsoft365_gateway_invoke, aws_iam_role_policy.hermes_gateway_policy_authorization]
}

resource "aws_bedrockagentcore_policy" "microsoft365_read" {
  for_each         = var.microsoft365_runtime_enabled ? local.microsoft365_tools : toset([])
  name             = "HermesMicrosoft365${replace(each.key, "-", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Read-only pinned consumer mail: ${each.key}. Runtime rejects unknown args, bounds queries and pins identity."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"
  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.microsoft365_action_prefix}${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${aws_cognito_resource_server.hermes.scope_identifiers[0]}*"
        };
      CEDAR
    }
  }
  depends_on = [aws_bedrockagentcore_gateway_target.microsoft365]
}
