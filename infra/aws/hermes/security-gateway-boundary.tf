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
# The security account's gateway, which is where every AWS call now goes.
#
#   Hermes -> this gateway -> security gateway -> AWS MCP Server -> AWS APIs
#
# The Hermes gateway cannot sign as another account's role: its outbound
# credential provider is `gateway_iam_role { service, region }`, which has no
# role-ARN field, and its execution role is shared by every target. So the last
# hop's identity has to live in the account that owns the boundary, and this
# gateway becomes a caller rather than a signer of AWS requests.
#
# There is deliberately ONE AWS target, not two. An earlier revision added a
# second AWS target alongside the existing one, which collided on tool names
# with it and would have exposed the AWS tools twice under two namespaces. The
# existing `aws` target is repointed instead, in aws-mcp-boundary.tf, and its
# manifest declares the resulting wire prefix so the client keeps the canonical
# aws___<tool> names.
# ---------------------------------------------------------------------------

locals {
  security_gateway_url = trimspace(var.security_gateway_url)
  security_gateway_arn = trimspace(var.security_gateway_arn)

  # Empty until the security stack has applied and its dependency reference has
  # flowed, which is what the speculative plan on a pull request sees.
  security_gateway_enabled = (
    local.security_gateway_url != "" && local.security_gateway_arn != ""
  )

  # A gateway-to-gateway call is SigV4-signed for the AgentCore service itself.
  # `aws-mcp` is the service for calling the AWS MCP Server directly, which is
  # what the security gateway does -- not what this one now does.
  security_gateway_sigv4_service = "bedrock-agentcore"
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
