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

  tools_agentcore_gateway_role_arn = "arn:aws:iam::${local.accounts["TOOLS"]}:role/hermes-agentcore-gateway"
}


data "aws_iam_policy_document" "security_gateway_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

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

resource "aws_iam_role_policy_attachment" "security_gateway_readonly" {
  role       = aws_iam_role.security_gateway.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/ReadOnlyAccess"
}

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


data "aws_iam_policy_document" "security_gateway_invocation" {
  statement {
    sid    = "AllowHermesGatewayRoleOnly"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = [local.tools_agentcore_gateway_role_arn]
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
      values   = [local.tools_agentcore_gateway_role_arn]
    }
  }
}

resource "aws_bedrockagentcore_resource_policy" "security_gateway" {
  resource_arn = aws_bedrockagentcore_gateway.security.gateway_arn
  policy       = data.aws_iam_policy_document.security_gateway_invocation.json

  depends_on = [aws_bedrockagentcore_gateway.security]
}


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
