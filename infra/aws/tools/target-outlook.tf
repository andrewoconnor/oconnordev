locals {
  outlook_target_name     = "outlook"
  outlook_manifest        = jsondecode(file("${local.adapter_root}/outlook-mcp-tools.json"))
  outlook_tools           = toset(local.outlook_manifest.tools)
  outlook_operations      = flatten([for path in values(local.outlook_openapi.paths) : [for method, operation in path : { method = method, id = operation.operationId }]])
  outlook_scopes          = ["https://graph.microsoft.com/Calendars.Read", "https://graph.microsoft.com/Mail.Read", "offline_access"]
  outlook_client_id       = "94add076-3186-458b-a837-6d417bafc4b3"
  outlook_cert_thumbprint = "vr1vT9cBCaEexLqlCPPG94I9Nvv5TtVi_u3nIsd5JAI"
}

resource "aws_bedrockagentcore_oauth2_credential_provider" "outlook" {
  name                       = "hermes-outlook"
  credential_provider_vendor = "CustomOauth2"

  oauth2_provider_config {
    custom_oauth2_provider_config {
      client_id                    = local.outlook_client_id
      client_authentication_method = "PRIVATE_KEY_JWT"

      oauth_discovery {
        discovery_url = "https://login.microsoftonline.com/consumers/v2.0/.well-known/openid-configuration"
      }

      private_key_jwt_config {
        signing_algorithm        = "PS256"
        additional_header_claims = { "x5t#S256" = local.outlook_cert_thumbprint }

        private_key_source {
          kms_key_source {
            kms_key_arn = aws_kms_key.outlook_signing.arn
          }
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = can(regex("^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$", local.outlook_cert_thumbprint))
      error_message = "outlook_cert_thumbprint must be the unpadded base64url SHA-256 printed by build_certificate.py."
    }
  }
}

data "aws_iam_policy_document" "outlook_target_credentials" {
  statement {
    sid     = "GetOutlookTokenFromAgentCoreIdentity"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetResourceOauth2Token"]

    resources = [
      aws_bedrockagentcore_oauth2_credential_provider.outlook.credential_provider_arn,
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:token-vault/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "SignOutlookClientAssertionsThroughAgentCoreIdentity"
    effect    = "Allow"
    actions   = ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = [aws_kms_key.outlook_signing.arn]

    condition {
      test     = "StringLike"
      variable = "kms:ViaService"
      values   = ["bedrock-agentcore-identity.*.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "outlook_target_credentials" {
  name   = "hermes-outlook-agentcore-credentials"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.outlook_target_credentials.json
}

resource "aws_bedrockagentcore_gateway_target" "outlook" {
  name               = local.outlook_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only Microsoft Graph mail and calendar for the owner's personal account, with user-delegated OAuth and a KMS-signed client assertion."

  credential_provider_configuration {
    oauth {
      provider_arn       = aws_bedrockagentcore_oauth2_credential_provider.outlook.credential_provider_arn
      scopes             = local.outlook_scopes
      grant_type         = "AUTHORIZATION_CODE"
      default_return_url = local.oauth_return_url
    }
  }

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = jsonencode(local.outlook_openapi)
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = alltrue([for operation in local.outlook_operations : operation.method == "get"]) && toset([for operation in local.outlook_operations : operation.id]) == local.outlook_tools && length(local.outlook_operations) == length(local.outlook_tools)
      error_message = "The Outlook OpenAPI spec must contain only GET operations, and its operation IDs must equal the adapter manifest."
    }
    precondition {
      condition     = local.outlook_scopes == ["https://graph.microsoft.com/Calendars.Read", "https://graph.microsoft.com/Mail.Read", "offline_access"]
      error_message = "The Outlook target must request only read-only mail and calendar scopes."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.outlook_target_credentials,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "outlook_read" {
  for_each = local.outlook_tools

  name             = "HermesOutlook${each.key}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only Outlook tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.outlook_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${aws_cognito_resource_server.hermes.scope_identifiers[0]}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.outlook]
}

output "outlook_oauth_callback_url" {
  description = "Add this URL as a Web redirect URI on the Entra app registration."
  value       = aws_bedrockagentcore_oauth2_credential_provider.outlook.callback_url
}
