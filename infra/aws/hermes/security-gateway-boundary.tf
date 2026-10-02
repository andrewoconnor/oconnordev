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
    condition     = var.security_gateway_arn == "" || can(regex("^arn:aws:bedrock-agentcore:[a-z0-9-]+:482921124454:gateway/[a-z0-9-]+$", var.security_gateway_arn))
    error_message = "Set a gateway ARN in account 482921124454. A wildcard or a different account would widen the Hermes gateway role beyond the one gateway it may call."
  }
}

# ---------------------------------------------------------------------------
# The security account's gateway, as a target of this gateway.
#
# This is the pivot away from putting the AWS identity in this account: the
# Hermes gateway cannot sign as another account's role, so it calls a gateway
# that can. Between the two, the trust boundary and the IAM permissions live in
# the security account; this file only says "this gateway, and nothing else".
#
# The upstream tool namespace is `awssec` rather than `aws` because the
# Hermes-account AWS target already owns aws___<tool>, and the adapter refuses
# two targets claiming one logical name. Renaming the upstream target is what
# keeps the two paths distinguishable without an adapter change.
# ---------------------------------------------------------------------------

locals {
  security_target_name = "security"

  security_gateway_url = trimspace(var.security_gateway_url)
  security_gateway_arn = trimspace(var.security_gateway_arn)

  # Generated from the same manifest the Hermes-account AWS target uses: the
  # security gateway fronts the same upstream server, so the tool set is
  # identical and only the namespace differs. Both the target and its Cedar
  # policies read from this, so a tool added upstream cannot leave the policy
  # set behind.
  security_action_by_tool = {
    for name in local.aws_native_tools :
    name => "${local.security_target_name}___${replace(name, "aws___", "awssec___")}"
  }

  # Empty until the security stack has applied and its dependency reference has
  # flowed, which is what the speculative plan on a pull request sees.
  # Everything below is gated on it, the same way the production stack gates
  # its CloudFront endpoint on hermes_gateway_origin_hostname.
  security_gateway_enabled = (
    local.security_gateway_url != "" && local.security_gateway_arn != ""
  )
}

data "aws_iam_policy_document" "hermes_gateway_security_gateway" {
  count = local.security_gateway_enabled ? 1 : 0

  # Scoped to the exact gateway ARN, never a wildcard: the resource policy on
  # the other side names this role, and this statement names that gateway, so
  # neither half can drift into a broader grant on its own.
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

resource "aws_bedrockagentcore_gateway_target" "security" {
  count = local.security_gateway_enabled ? 1 : 0

  name               = local.security_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only AWS access through the security account's gateway, which owns the IAM boundary."

  # SigV4 with this gateway's role. The security gateway is AWS_IAM inbound, so
  # the signature is the whole authentication story -- there is no token to
  # carry and no Cognito user to authorize.
  credential_provider_configuration {
    gateway_iam_role {
      service = "bedrock-agentcore"
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

  depends_on = [aws_iam_role_policy.hermes_gateway_security_gateway]
}

# Cedar still governs the human caller: the security gateway deliberately has no
# policy engine, because Cedar's principals are OAuth users and an IAM caller
# would not match them. Authorization lives here, on the gateway the user
# actually reaches.
resource "aws_bedrockagentcore_policy" "security_tool" {
  for_each = local.security_gateway_enabled ? local.security_action_by_tool : {}

  name             = "HermesSecurity${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the security-account tool ${each.value} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${each.value}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${local.hermes_aws_required_scope}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.security]
}

output "hermes_security_target_name" {
  description = "Gateway target name that prefixes the security-account AWS tools."
  value       = local.security_target_name
}
