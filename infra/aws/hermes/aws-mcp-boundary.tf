locals {
  hermes_aws_target_name = "aws"
  aws_tool_manifest      = jsondecode(file("${local.adapter_root}/aws-mcp-tools.json"))
  # Mirrors the adapter's Target.prefix: the manifest's declared wire prefix,
  # or the plain target prefix when it declares none. One source of truth, so a
  # policy cannot drift from the name the adapter actually sends.
  hermes_aws_action_prefix = try(local.aws_tool_manifest.gateway_action_prefix, "${local.hermes_aws_target_name}___")
  aws_native_tools         = toset(local.aws_tool_manifest.tools)

  hermes_aws_required_scope = aws_cognito_resource_server.hermes.scope_identifiers[0]
}

# ReadOnlyAccess used to be attached to the gateway role here, because the AWS
# target signed with that role and called the AWS MCP Server directly. The
# target now calls the security account's gateway, so the identity that reaches
# AWS APIs is the security role and this grant backed nothing. Removing it also
# removes the gateway role's ability to read every resource in this account.

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

# The upstream is the security account's gateway, not the AWS MCP Server, so
# this target is a caller rather than a signer of AWS requests. Only one AWS
# target exists: the AWS tools come *through* the security gateway, rather than
# alongside a second copy of themselves.
resource "aws_bedrockagentcore_gateway_target" "aws" {
  count = local.security_gateway_enabled ? 1 : 0

  name               = local.hermes_aws_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only AWS access, routed through the security account's gateway, which holds the identity that reaches AWS APIs."

  # A gateway-to-gateway hop is SigV4-signed for the AgentCore service itself.
  # Signing with `aws-mcp` here would address the wrong service and fail.
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

# The client keeps the canonical aws___<tool> names even though the wire action
# is aws___aws___aws___<tool>. Both sides read the prefix from the same manifest
# key, so the permit cannot drift from the name the adapter actually sends.
#
# Gated on the same value as the target, and for the same reason: a Cedar action
# name exists only while the target that advertises it exists. Creating the
# permits without the target makes the policy engine reject them as unrecognized
# actions, which fails the apply outright and takes the AWS tools away entirely
# rather than leaving them simply unavailable.
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

output "hermes_aws_mcp_target_name" {
  description = "Gateway target name that prefixes the AWS MCP tools."
  value       = local.hermes_aws_target_name
}
