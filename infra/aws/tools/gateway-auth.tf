locals {
  hermes_cognito_domain = "hermes-mcp-${data.aws_caller_identity.current.account_id}"
  cognito_issuer        = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.hermes.id}"
  cognito_token_url     = "https://${aws_cognito_user_pool_domain.hermes.domain}.auth.${data.aws_region.current.region}.amazoncognito.com/oauth2/token"
}

resource "aws_cognito_user_pool" "hermes" {
  name = "hermes-mcp-m2m"
}

resource "aws_cognito_resource_server" "hermes" {
  user_pool_id = aws_cognito_user_pool.hermes.id
  identifier   = "hermes-mcp"
  name         = "Hermes MCP gateway"

  scope {
    scope_name        = "invoke"
    scope_description = "Invoke the shared Hermes MCP Gateway."
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cognito_user_pool_domain" "hermes" {
  domain       = local.hermes_cognito_domain
  user_pool_id = aws_cognito_user_pool.hermes.id
}

resource "aws_cognito_user_pool_client" "hermes" {
  name                                 = "hermes-mcp-local-adapter"
  user_pool_id                         = aws_cognito_user_pool.hermes.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = [aws_cognito_resource_server.hermes.scope_identifiers[0]]
  supported_identity_providers         = ["COGNITO"]
  access_token_validity                = 5

  token_validity_units {
    access_token = "minutes"
  }
}
