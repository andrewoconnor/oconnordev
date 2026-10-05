data "aws_region" "current" {}

data "aws_partition" "current" {}

locals {
  hermes_gateway_name       = "hermes"
  hermes_policy_engine_name = "hermes_policy_engine"
  gateway_scope             = "hermes-mcp/invoke"
}

resource "aws_bedrockagentcore_policy_engine" "hermes" {
  name        = local.hermes_policy_engine_name
  description = "Default-deny Cedar guardrails for Hermes MCP targets and tools."
}

data "aws_iam_policy_document" "hermes_gateway_trust" {
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
      values   = ["arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:gateway/*"]
    }
  }
}

resource "aws_iam_role" "hermes_gateway" {
  name               = "hermes-agentcore-gateway"
  assume_role_policy = data.aws_iam_policy_document.hermes_gateway_trust.json
}

data "aws_iam_policy_document" "hermes_gateway_core" {
  statement {
    sid     = "GetGatewayWorkloadAccessToken"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetWorkloadAccessToken"]
    resources = [
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "ReadGatewayPolicyEngine"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:GetPolicyEngine"]
    resources = [aws_bedrockagentcore_policy_engine.hermes.policy_engine_arn]
  }
}

data "aws_iam_policy_document" "hermes_gateway_policy_authorization" {
  statement {
    sid    = "AuthorizeGatewayActions"
    effect = "Allow"
    actions = [
      "bedrock-agentcore:AuthorizeAction",
      "bedrock-agentcore:PartiallyAuthorizeActions",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:policy-engine/${local.hermes_policy_engine_name}*",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:gateway/${local.hermes_gateway_name}*",
    ]
  }
}

resource "aws_iam_role_policy" "hermes_gateway_core" {
  name   = "hermes-agentcore-core"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.hermes_gateway_core.json
}

resource "aws_iam_role_policy" "hermes_gateway_policy_authorization" {
  name   = "hermes-agentcore-policy"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.hermes_gateway_policy_authorization.json
}

resource "aws_bedrockagentcore_gateway" "hermes" {
  name            = local.hermes_gateway_name
  role_arn        = aws_iam_role.hermes_gateway.arn
  authorizer_type = "CUSTOM_JWT"
  protocol_type   = "MCP"

  authorizer_configuration {
    custom_jwt_authorizer {
      discovery_url   = "${local.cognito_issuer}/.well-known/openid-configuration"
      allowed_clients = [aws_cognito_user_pool_client.hermes.id]
      allowed_scopes  = [aws_cognito_resource_server.hermes.scope_identifiers[0]]

      custom_claim {
        inbound_token_claim_name       = "token_use"
        inbound_token_claim_value_type = "STRING"

        authorizing_claim_match_value {
          claim_match_operator = "EQUALS"

          claim_match_value {
            match_value_string = "access"
          }
        }
      }
    }
  }

  policy_engine_configuration {
    arn  = aws_bedrockagentcore_policy_engine.hermes.policy_engine_arn
    mode = "ENFORCE"
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}
