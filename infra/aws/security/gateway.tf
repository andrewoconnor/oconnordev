variable "security_aws_mcp_endpoint" {
  description = "AWS MCP Server endpoint fronted by the security gateway's AWS target."
  type        = string
  default     = "https://aws-mcp.us-east-1.api.aws/mcp"

  validation {
    condition     = can(regex("^https://aws-mcp\\.[a-z0-9-]+\\.api\\.aws/mcp$", var.security_aws_mcp_endpoint))
    error_message = "security_aws_mcp_endpoint must be an https AWS MCP Server endpoint of the form https://aws-mcp.<region>.api.aws/mcp."
  }
}

variable "security_aws_mcp_sigv4_service" {
  description = "SigV4 service name this gateway uses to sign requests to the AWS MCP Server. Pinned so the signature cannot silently follow a changed endpoint."
  type        = string
  default     = "aws-mcp"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,63}$", var.security_aws_mcp_sigv4_service))
    error_message = "security_aws_mcp_sigv4_service must be a lowercase AWS service name."
  }
}

locals {
  security_region = "us-east-1"

  security_gateway_name    = "oconnordev-security"
  security_aws_target_name = "aws"

  # The Hermes gateway's execution role, in the Hermes account. Both accounts
  # and both names are already fixed literals elsewhere in this repository, so
  # this is a deliberate cross-account reference rather than a Spacelift
  # output/input pair -- nothing here needs the security stack to be ordered
  # against the Hermes stack.
  hermes_gateway_role_arn = "arn:aws:iam::421680664125:role/hermes-agentcore-gateway"
}

# ---------------------------------------------------------------------------
# The security account's own AgentCore Gateway: the AWS trust boundary.
#
# The Hermes gateway cannot reach another account's AWS APIs. Its outbound
# credential provider is `gateway_iam_role { service, region }`, which has no
# role-ARN field, so it always signs as the Hermes role -- and `run_script`
# cannot assume a second identity either. A gateway in the security account is
# the way across: the Hermes gateway becomes a *caller* of this gateway, and the
# IAM identity that actually reaches the AWS APIs lives here.
#
# Inbound auth must be AWS_IAM, not CUSTOM_JWT. A gateway can only be
# configured with one or the other at creation time, and only under SigV4 may a
# resource policy name specific principals. OAuth forces a wildcard principal,
# which would defeat the point of owning the boundary in this account.
#
#   https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html
#   "An Agent Runtime or Gateway can only be configured with either SigV4 OR
#    OAuth authentication at creation time, not both simultaneously."
#
# No policy engine is attached. Cedar's principals are OAuth users
# (`principal is AgentCore::OAuthUser`), so an ENFORCE-mode engine with no
# policy matching an IAM caller would deny every call; the boundary here is the
# resource policy below plus the role's own IAM. Authorization for the human
# caller stays where it already is -- the Hermes gateway's Cedar policies.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "security_gateway_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    # Confused-deputy protection: only an AgentCore Gateway in this account may
    # assume this role.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:bedrock-agentcore:${local.security_region}:${data.aws_caller_identity.current.account_id}:gateway/*"]
    }
  }
}

resource "aws_iam_role" "security_gateway" {
  name               = "oconnordev-security-gateway"
  assume_role_policy = data.aws_iam_policy_document.security_gateway_trust.json
}

# Broad read, deliberately. This account is the organization's read vantage
# point, so its identity is meant to see everything the aggregated services
# describe. The narrow Hermes-account grants are untouched.
resource "aws_iam_role_policy_attachment" "security_gateway_readonly" {
  role       = aws_iam_role.security_gateway.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/ReadOnlyAccess"
}

# ...but "read-only" is not the same as "harmless". ReadOnlyAccess includes the
# APIs that return secret material and credentials, which is exactly a
# security-tooling account's exfiltration surface. These are denied explicitly;
# an explicit Deny is evaluated first, so it holds regardless of anything
# attached later.
data "aws_iam_policy_document" "security_gateway_secret_denies" {
  statement {
    sid    = "DenySecretAndCredentialReturningApis"
    effect = "Deny"

    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:BatchGetSecretValue",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "kms:Decrypt",
      "kms:ReEncryptFrom",
      "iam:GetCredentialReport",
      "iam:GetLoginProfile",
      "sts:GetFederationToken",
      "sts:GetSessionToken",
      "sts:AssumeRole",
    ]

    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "security_gateway_secret_denies" {
  name   = "oconnordev-security-gateway-secret-denies"
  role   = aws_iam_role.security_gateway.id
  policy = data.aws_iam_policy_document.security_gateway_secret_denies.json

  lifecycle {
    precondition {
      condition = length([
        for statement in jsondecode(data.aws_iam_policy_document.security_gateway_secret_denies.json).Statement :
        statement if can(statement.Resource) && can(statement.NotResource)
      ]) == 0
      error_message = "Each deny statement must set either Resource or NotResource, never both; the IAM API rejects a statement that sets both."
    }
  }
}

resource "aws_bedrockagentcore_gateway" "security" {
  name            = local.security_gateway_name
  role_arn        = aws_iam_role.security_gateway.arn
  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"

  depends_on = [
    aws_iam_role_policy.security_gateway_secret_denies,
    aws_iam_role_policy_attachment.security_gateway_readonly,
  ]
}

# ---------------------------------------------------------------------------
# Invocation is restricted to the Hermes gateway's execution role.
#
# The Allow names one principal; the Deny is what makes that an allowlist
# rather than a formality, because a permissive identity policy in the Hermes
# account would otherwise be enough to invoke this gateway.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "security_gateway_invocation" {
  statement {
    sid    = "AllowHermesGatewayRoleOnly"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [local.hermes_gateway_role_arn]
    }

    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [aws_bedrockagentcore_gateway.security.gateway_arn]
  }

  statement {
    sid    = "DenyEveryOtherPrincipal"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [aws_bedrockagentcore_gateway.security.gateway_arn]

    condition {
      test     = "ArnNotEquals"
      variable = "aws:PrincipalArn"
      values   = [local.hermes_gateway_role_arn]
    }
  }
}

resource "aws_bedrockagentcore_resource_policy" "security_gateway" {
  resource_arn = aws_bedrockagentcore_gateway.security.gateway_arn
  policy       = data.aws_iam_policy_document.security_gateway_invocation.json

  depends_on = [aws_bedrockagentcore_gateway.security]
}

# ---------------------------------------------------------------------------
# AWS's managed MCP Server, reached with this gateway's own role.
#
# This is the only path to AWS. The Hermes gateway's `aws` target points at
# *this* gateway rather than at the AWS MCP Server, so there is exactly one set
# of AWS tools and exactly one identity reaching AWS APIs -- this role.
#
# The target name still contributes a prefix, and that is unavoidable rather
# than a naming choice: AgentCore prefixes every action with the target's name
# and the server already namespaces its own tools with `aws___`, so this
# gateway advertises `aws___aws___<tool>` and the Hermes gateway adds a third
# prefix on top. The Hermes adapter keeps the client-visible names canonical
# by declaring that wire prefix in the AWS manifest, so the nesting never
# reaches Hermes' tool names.
# ---------------------------------------------------------------------------

resource "aws_bedrockagentcore_gateway_target" "aws" {
  name               = local.security_aws_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.security.gateway_id
  description        = "Read-only AWS access in the security account, signed with this gateway's role."

  credential_provider_configuration {
    gateway_iam_role {
      service = var.security_aws_mcp_sigv4_service
      region  = local.security_region
    }
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint     = var.security_aws_mcp_endpoint
        listing_mode = "DEFAULT"
      }
    }
  }

  depends_on = [
    aws_bedrockagentcore_gateway.security,
    aws_iam_role_policy.security_gateway_secret_denies,
  ]
}

output "security_gateway_id" {
  description = "Gateway ID of the security account's AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.security.gateway_id
}

output "security_gateway_arn" {
  description = "ARN of the security account's AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.security.gateway_arn
}

output "security_gateway_url" {
  description = "MCP endpoint of the security account's gateway, consumed by the Hermes gateway target."
  value       = aws_bedrockagentcore_gateway.security.gateway_url
}
