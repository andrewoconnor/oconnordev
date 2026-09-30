moved {
  from = aws_bedrockagentcore_gateway.github
  to   = aws_bedrockagentcore_gateway.hermes
}

moved {
  from = aws_bedrockagentcore_policy_engine.github
  to   = aws_bedrockagentcore_policy_engine.hermes
}

moved {
  from = aws_iam_role.github_gateway
  to   = aws_iam_role.hermes_gateway
}

moved {
  from = aws_iam_role_policy.github_gateway_credentials
  to   = aws_iam_role_policy.github_target_credentials
}

moved {
  from = aws_iam_role_policy.github_gateway_policy_authorization
  to   = aws_iam_role_policy.hermes_gateway_policy_authorization
}

moved {
  from = aws_cognito_user_pool.github
  to   = aws_cognito_user_pool.hermes
}

moved {
  from = aws_cognito_resource_server.github
  to   = aws_cognito_resource_server.hermes
}

moved {
  from = aws_cognito_user_pool_domain.github
  to   = aws_cognito_user_pool_domain.hermes
}

moved {
  from = aws_cognito_user_pool_client.github
  to   = aws_cognito_user_pool_client.hermes
}
