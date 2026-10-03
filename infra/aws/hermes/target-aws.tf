locals {
  hermes_aws_target_name   = "aws"
  aws_tool_manifest        = jsondecode(file("${local.adapter_root}/aws-mcp-tools.json"))
  hermes_aws_action_prefix = try(local.aws_tool_manifest.gateway_action_prefix, "${local.hermes_aws_target_name}___")
  aws_native_tools         = toset(local.aws_tool_manifest.tools)

  hermes_aws_required_scope = aws_cognito_resource_server.hermes.scope_identifiers[0]
}


locals {
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
  count = local.security_gateway_enabled ? 1 : 0

  name               = local.hermes_aws_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only AWS access, routed through the security account's gateway, which holds the identity that reaches AWS APIs."

  credential_provider_configuration {
    gateway_iam_role {
      service = local.security_gateway_sigv4_service
      region  = data.aws_region.current.region
    }
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint     = local.security_gateway_url
        listing_mode = "DEFAULT"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = length(local.aws_native_tools) == 7
      error_message = "The AWS MCP manifest must contain exactly the seven tool names covered by the Cedar policies and the Hermes adapter allowlist."
    }

    precondition {
      condition     = endswith(local.hermes_aws_action_prefix, "___")
      error_message = "The AWS manifest's gateway_action_prefix must end with the ___ separator, or the Cedar action would not match the name the adapter sends."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.hermes_gateway_readonly_guardrails,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
    aws_iam_role_policy.hermes_gateway_security_gateway,
  ]
}

resource "aws_bedrockagentcore_policy" "aws_tool" {
  for_each = local.security_gateway_enabled ? local.aws_native_tools : toset([])

  name             = "HermesAWS${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only AWS MCP tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.hermes_aws_action_prefix}${each.key}",
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

variable "security_gateway_url" {
  description = "MCP endpoint of the security account's AgentCore Gateway, exported by that stack through a Spacelift dependency reference."
  type        = string
  default     = ""

  validation {
    condition     = var.security_gateway_url == "" || can(regex("^https://[a-z0-9-]+\\.gateway\\.bedrock-agentcore\\.[a-z0-9-]+\\.amazonaws\\.com/mcp$", var.security_gateway_url))
    error_message = "Set the security gateway's MCP endpoint only (no additional path or credentials)."
  }
}

variable "security_gateway_arn" {
  description = "ARN of the security account's AgentCore Gateway, exported by that stack through a Spacelift dependency reference. Scopes the Hermes gateway role's invoke permission to exactly that gateway."
  type        = string
  default     = ""

  validation {
    condition     = var.security_gateway_arn == "" || can(regex("^arn:aws:bedrock-agentcore:[a-z0-9-]+:${local.accounts["SECURITY"]}:gateway/[a-z0-9-]+$", var.security_gateway_arn))
    error_message = "Set a gateway ARN in account ${local.accounts["SECURITY"]}. A wildcard or a different account would widen the Hermes gateway role beyond the one gateway it may call."
  }
}


locals {
  security_gateway_url = trimspace(var.security_gateway_url)
  security_gateway_arn = trimspace(var.security_gateway_arn)

  security_gateway_enabled = (
    local.security_gateway_url != "" && local.security_gateway_arn != ""
  )

  security_gateway_sigv4_service = "bedrock-agentcore"
}

data "aws_iam_policy_document" "hermes_gateway_security_gateway" {
  count = local.security_gateway_enabled ? 1 : 0

  statement {
    sid       = "InvokeSecurityGatewayOnly"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [local.security_gateway_arn]
  }
}

resource "aws_iam_role_policy" "hermes_gateway_security_gateway" {
  count = local.security_gateway_enabled ? 1 : 0

  name   = "hermes-agentcore-security-gateway"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.hermes_gateway_security_gateway[0].json
}
