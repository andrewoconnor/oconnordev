locals {
  google_target_name     = "google"
  google_manifest        = jsondecode(file("${local.adapter_root}/google-mcp-tools.json"))
  google_tools           = toset(local.google_manifest.tools)
  google_operations      = flatten([for path in values(local.google_openapi.paths) : [for method, operation in path : { method = method, id = operation.operationId }]])
  google_scopes          = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/gmail.readonly"]
  google_return_url      = "http://localhost:9090/oauth2/callback"
  google_oauth_client_id = "693193037198-cgg4gr2q675dt3t18c74uhafgbrfdle3.apps.googleusercontent.com"
  google_oauth_secret_arns = compact([
    data.aws_secretsmanager_secret.google_oauth_client.arn,
    try(aws_bedrockagentcore_oauth2_credential_provider.google.client_secret_arn[0].secret_arn, ""),
  ])
}

data "aws_secretsmanager_secret" "google_oauth_client" {
  name = "/hermes/google/oauth-client-secret"
}

resource "aws_bedrockagentcore_oauth2_credential_provider" "google" {
  name                       = "hermes-google"
  credential_provider_vendor = "GoogleOauth2"

  oauth2_provider_config {
    google_oauth2_provider_config {
      client_id            = local.google_oauth_client_id
      client_secret_source = "EXTERNAL"

      client_secret_config {
        secret_id = data.aws_secretsmanager_secret.google_oauth_client.arn
        json_key  = "client_secret"
      }
    }
  }
}

data "aws_iam_policy_document" "google_target_credentials" {
  statement {
    sid     = "GetUserBoundWorkloadAccessToken"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetWorkloadAccessTokenForJWT", "bedrock-agentcore:GetWorkloadAccessTokenForUserId"]

    resources = [
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid     = "GetGoogleTokenFromAgentCoreIdentity"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetResourceOauth2Token"]

    resources = [
      aws_bedrockagentcore_oauth2_credential_provider.google.credential_provider_arn,
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:token-vault/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "ReadGoogleOauthClientSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = local.google_oauth_secret_arns
  }
}

resource "aws_iam_role_policy" "google_target_credentials" {
  name   = "hermes-google-agentcore-credentials"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.google_target_credentials.json
}

resource "aws_bedrockagentcore_gateway_target" "google" {
  name               = local.google_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only Gmail and Google Calendar APIs for the owner's account, with user-delegated Google OAuth through AgentCore Identity."

  credential_provider_configuration {
    oauth {
      provider_arn       = aws_bedrockagentcore_oauth2_credential_provider.google.credential_provider_arn
      scopes             = local.google_scopes
      grant_type         = "AUTHORIZATION_CODE"
      default_return_url = local.google_return_url
    }
  }

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = jsonencode(local.google_openapi)
        }
      }
    }
  }

  lifecycle {
    precondition {
      condition     = alltrue([for operation in local.google_operations : operation.method == "get"]) && toset([for operation in local.google_operations : operation.id]) == local.google_tools && length(local.google_operations) == length(local.google_tools)
      error_message = "The Google OpenAPI spec must contain only GET operations, and its operation IDs must equal the adapter manifest."
    }
    precondition {
      condition     = local.google_scopes == ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/gmail.readonly"]
      error_message = "Google targets must request only the read-only Calendar and Gmail scopes."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.google_target_credentials,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

resource "aws_bedrockagentcore_policy" "google_read" {
  for_each = local.google_tools

  name             = "HermesGoogle${each.key}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only Google tool ${each.key} to callers holding the gateway scope."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"${local.google_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${aws_cognito_resource_server.hermes.scope_identifiers[0]}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.google]
}

output "google_oauth_callback_url" {
  description = "Add this URL to the Google Web OAuth client's authorized redirect URIs."
  value       = aws_bedrockagentcore_oauth2_credential_provider.google.callback_url
}
