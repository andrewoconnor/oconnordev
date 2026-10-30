
mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  mock_resource "aws_ecr_repository" {
    defaults = {
      repository_url = "421680664125.dkr.ecr.us-east-1.amazonaws.com/oconnordev-tools"
    }
  }

  mock_resource "aws_lambda_function_url" {
    defaults = {
      function_url = "https://synthetic.lambda-url.us-east-1.on.aws/"
    }
  }

  mock_data "aws_secretsmanager_secret" {
    defaults = {
      arn = "arn:aws:secretsmanager:us-east-1:421680664125:secret:/hermes/mock-Ab12Cd"
    }
  }

  mock_resource "aws_bedrockagentcore_oauth2_credential_provider" {
    defaults = {
      credential_provider_arn = "arn:aws:bedrock-agentcore:us-east-1:421680664125:token-vault/default/oauth2credentialprovider/hermes-google"
      callback_url            = "https://bedrock-agentcore.us-east-1.amazonaws.com/identities/oauth2/callback/00000000-0000-0000-0000-000000000000"
    }
  }

  mock_resource "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-1:421680664125:key/00000000-0000-0000-0000-000000000000"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::421680664125:role/mock"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:421680664125:log-group:/aws/vendedlogs/bedrock-agentcore/gateway/hermes:*"
    }
  }

  mock_resource "aws_cognito_resource_server" {
    defaults = {
      scope_identifiers = ["hermes-mcp/invoke"]
    }
  }

  mock_resource "aws_bedrockagentcore_policy_engine" {
    defaults = {
      policy_engine_arn = "arn:aws:bedrock-agentcore:us-east-1:421680664125:policy-engine/hermes_policy_engine-abcdef1234"
      policy_engine_id  = "hermes_policy_engine-abcdef1234"
    }
  }

  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:us-east-1:421680664125:hermes-spacelift-rotation-mock"
      id  = "https://sqs.us-east-1.amazonaws.com/421680664125/hermes-spacelift-rotation-mock"
    }
  }

  mock_resource "aws_lambda_function" {
    defaults = {
      arn = "arn:aws:lambda:us-east-1:421680664125:function:hermes-spacelift-session-token-rotation"
    }
  }

  mock_resource "aws_cloudwatch_event_rule" {
    defaults = {
      arn = "arn:aws:events:us-east-1:421680664125:rule/hermes-spacelift-session-token-rotation"
    }
  }

  mock_resource "aws_bedrockagentcore_gateway" {
    defaults = {
      gateway_arn = "arn:aws:bedrock-agentcore:us-east-1:421680664125:gateway/hermes-mock"
      gateway_id  = "hermes-mock"
    }
  }

  mock_resource "aws_bedrockagentcore_api_key_credential_provider" {
    defaults = {
      credential_provider_arn = "arn:aws:acps:us-east-1:421680664125:token-vault/default/apikeycredentialprovider/hermes-mock"
    }
  }

  mock_resource "aws_cloudwatch_log_delivery_destination" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:421680664125:delivery-destination:hermes-gateway-application-logs"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "421680664125"
    }
  }

  mock_data "aws_region" {
    defaults = {
      region = "us-east-1"
      name   = "us-east-1"
    }
  }
}

variables {
  spacelift_run_id = "terraform-test"
  github_ruleset_cedar_schema = {
    gateway_arn        = "arn:aws:bedrock-agentcore:us-east-1:421680664125:gateway/hermes-mock"
    level_entity_type  = "AgentCore::ID_8d56337199_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_level"
    method_entity_type = "AgentCore::ID_e312b33e9c_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_method"
  }
}


run "plaid_native_boundary" {
  command = plan

  assert {
    condition     = aws_secretsmanager_secret.plaid.name == "/hermes/plaid/credentials" && aws_lambda_function.plaid.environment[0].variables == tomap({ SECRETS_ARN = aws_secretsmanager_secret.plaid.arn })
    error_message = "Only the secret ARN may enter Lambda environment; IaC owns an empty secret container."
  }

  assert {
    condition = jsondecode(aws_iam_role_policy.plaid.policy).Statement == [
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.plaid.arn] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.plaid.arn}:*"] }
    ]
    error_message = "Runtime may only read its own secret and write its own logs."
  }

  assert {
    condition = jsondecode(aws_iam_role_policy.plaid_gateway_invoke.policy).Statement == [
      { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [aws_lambda_function.plaid.arn] }
    ] && length(aws_bedrockagentcore_gateway_target.plaid.credential_provider_configuration[0].gateway_iam_role) == 1
    error_message = "Gateway uses only exact native Lambda invocation, not secret access or OAuth."
  }

  assert {
    condition     = aws_lambda_function.plaid.architectures == tolist(["arm64"]) && aws_lambda_function.plaid.runtime == "python3.13" && aws_lambda_function.plaid.handler == "plaid.handler" && aws_lambda_function.plaid.timeout < 15 && length(aws_lambda_function.plaid.vpc_config) == 0
    error_message = "Plaid must be a bounded ARM Python ZIP Lambda without VPC/NAT."
  }

  assert {
    condition = toset([for t in local.plaid_tool_schemas : t.name]) == local.plaid_tools && length(aws_bedrockagentcore_policy.plaid_read) == 7 && local.plaid_read_endpoints == {
      getAccounts              = "/accounts/get"
      getTransactions          = "/transactions/get"
      getItemStatus            = "/item/get"
      getRecurringTransactions = "/transactions/recurring/get"
      getLiabilities           = "/liabilities/get"
      getHoldings              = "/investments/holdings/get"
    }
    error_message = "Catalog exposes only local discovery and the six fixed semantic read POSTs."
  }

  assert {
    condition     = alltrue([for name, policy in aws_bedrockagentcore_policy.plaid_read : strcontains(policy.definition[0].cedar[0].statement, "plaid___${name}") && strcontains(policy.definition[0].cedar[0].statement, "principal.hasTag(\"scope\")")])
    error_message = "Each native action needs a scoped permit."
  }
}
