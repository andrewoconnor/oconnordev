variable "hermes_aws_mcp_endpoint" {
  description = "AWS MCP Server endpoint fronted by the shared gateway target."
  type        = string
  default     = "https://aws-mcp.us-east-1.api.aws/mcp"

  validation {
    condition     = can(regex("^https://aws-mcp\\.[a-z0-9-]+\\.api\\.aws/mcp$", var.hermes_aws_mcp_endpoint))
    error_message = "hermes_aws_mcp_endpoint must be an https AWS MCP Server endpoint of the form https://aws-mcp.<region>.api.aws/mcp."
  }
}

variable "hermes_aws_mcp_sigv4_service" {
  description = "SigV4 service name the gateway uses to sign requests to the AWS MCP Server. The MCP proxy for AWS infers this from the endpoint hostname; it is pinned here so the signature cannot silently follow a changed endpoint."
  type        = string
  default     = "aws-mcp"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,63}$", var.hermes_aws_mcp_sigv4_service))
    error_message = "hermes_aws_mcp_sigv4_service must be a lowercase AWS service name."
  }
}

locals {
  hermes_aws_target_name  = "aws"
  aws_tool_manifest       = jsondecode(file("${local.adapter_root}/aws-mcp-tools.json"))
  aws_native_tools        = toset(local.aws_tool_manifest.tools)
  hermes_aws_readonly_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/ReadOnlyAccess"

  hermes_aws_required_scope = aws_cognito_resource_server.hermes.scope_identifiers[0]
}

resource "aws_iam_role_policy_attachment" "hermes_gateway_readonly" {
  role       = aws_iam_role.hermes_gateway.name
  policy_arn = local.hermes_aws_readonly_arn
}

locals {
  # The gateway execution role may read exactly these secrets at runtime, one
  # per upstream credential. Additions belong here and nowhere else, so that
  # granting a new upstream credential is a deliberate, reviewable diff rather
  # than a side effect of a tag or a path prefix. The long-lived Spacelift API
  # key is deliberately absent: only the short-lived session token is readable
  # by the gateway.
  hermes_gateway_readable_secret_arns = [
    aws_secretsmanager_secret.github_machine_user_pat.arn,
    aws_secretsmanager_secret.spacelift_session_token.arn,
  ]
}

data "aws_iam_policy_document" "hermes_gateway_readonly_guardrails" {
  statement {
    sid     = "DenySecretValueReadsOutsideApprovedRuntimeCredentials"
    effect  = "Deny"
    actions = ["secretsmanager:GetSecretValue"]

    not_resources = local.hermes_gateway_readable_secret_arns
  }
}

resource "aws_iam_role_policy" "hermes_gateway_readonly_guardrails" {
  name   = "hermes-agentcore-readonly-guardrails"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.hermes_gateway_readonly_guardrails.json

  lifecycle {
    precondition {
      condition = length([
        for statement in jsondecode(data.aws_iam_policy_document.hermes_gateway_readonly_guardrails.json).Statement :
        statement if can(statement.Resource) && can(statement.NotResource)
      ]) == 0
      error_message = "Each guardrail statement must set either Resource or NotResource, never both; the IAM API rejects a statement that sets both."
    }

    precondition {
      condition = alltrue([
        for arn in local.hermes_gateway_readable_secret_arns :
        !strcontains(arn, "*")
      ])
      error_message = "hermes_gateway_readable_secret_arns must name individual secret ARNs. A wildcard or path prefix would turn a per-credential allowlist back into a broad match."
    }

    precondition {
      condition = alltrue([
        for arn in local.hermes_gateway_readable_secret_arns :
        !strcontains(arn, var.hermes_spacelift_api_key_secret_name)
      ])
      error_message = "The gateway execution role must never be able to read the long-lived Spacelift API key. Only the short-lived session-token secret belongs in hermes_gateway_readable_secret_arns."
    }
  }
}

resource "aws_bedrockagentcore_gateway_target" "aws" {
  name               = local.hermes_aws_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only AWS access through AWS's managed MCP Server, signed with the gateway role."

  credential_provider_configuration {
    gateway_iam_role {
      service = var.hermes_aws_mcp_sigv4_service
      region  = data.aws_region.current.region
    }
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint     = var.hermes_aws_mcp_endpoint
        listing_mode = "DEFAULT"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = length(local.aws_native_tools) == 7
      error_message = "The AWS MCP manifest must contain exactly the seven tool names covered by the Cedar policies and the Hermes adapter allowlist."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.hermes_gateway_readonly_guardrails,
    aws_iam_role_policy_attachment.hermes_gateway_readonly,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "aws_tool" {
  for_each = local.aws_native_tools

  name             = "HermesAWS${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only AWS MCP tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.hermes_aws_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${local.hermes_aws_required_scope}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.aws]
}

output "hermes_aws_mcp_endpoint" {
  description = "AWS MCP Server endpoint fronted by the shared gateway."
  value       = var.hermes_aws_mcp_endpoint
}

output "hermes_aws_mcp_target_name" {
  description = "Gateway target name that prefixes the AWS MCP tools."
  value       = local.hermes_aws_target_name
}