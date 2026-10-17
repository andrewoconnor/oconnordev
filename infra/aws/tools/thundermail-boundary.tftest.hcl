
mock_provider "aws" {
  # Policy preconditions decode Statement during plan, so return a minimal
  # valid policy document instead of the mock provider's generated placeholder.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  # Keep computed values consumed by provider-side argument validation valid.
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
      arn = "arn:aws:sqs:us-east-1:421680664125:***"
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

  # Generated placeholders for these break argument validation (a random
  # partition fails the ARN regex), so pin them to this stack's real values.
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
mock_provider "archive" {}

variables {
  spacelift_run_id = "terraform-test"
  # Offline gateway fixture: explicit binding, not a claim of a live mock schema.
  github_ruleset_cedar_schema = {
    gateway_arn        = "arn:aws:bedrock-agentcore:us-east-1:421680664125:gateway/hermes-mock"
    level_entity_type  = "AgentCore::ID_8d56337199_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_level"
    method_entity_type = "AgentCore::ID_e312b33e9c_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_method"
  }
}


run "thundermail_boundary" {
  command = plan
  assert {
    condition     = length(aws_bedrockagentcore_policy.thundermail_read) == 3 && aws_lambda_function.thundermail.image_uri == "421680664125.dkr.ecr.us-east-1.amazonaws.com/oconnordev-tools@${local.thundermail_image_digest}"
    error_message = "Three Cedar read permits and the pinned image digest."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.thundermail_gateway_invoke.policy).Statement[0].Action == ["lambda:InvokeFunction"] && jsondecode(aws_iam_role_policy.thundermail_gateway_invoke.policy).Statement[0].Resource == [local.thundermail_function_arn]
    error_message = "Gateway gets exact function invoke only, no secret/URL grants."
  }
  assert {
    condition     = length(jsondecode(aws_iam_role_policy.thundermail_runtime.policy).Statement) == 2 && jsondecode(aws_iam_role_policy.thundermail_runtime.policy).Statement[0].Action == ["secretsmanager:GetSecretValue"] && jsondecode(aws_iam_role_policy.thundermail_runtime.policy).Statement[0].Resource == [aws_secretsmanager_secret.thundermail.arn]
    error_message = "Runtime gets exact secret read, no write."
  }
  assert {
    condition     = aws_lambda_function.thundermail.architectures == tolist(["arm64"]) && aws_lambda_function.thundermail.package_type == "Image" && aws_lambda_function.thundermail.environment[0].variables.THUNDERMAIL_CREDENTIAL_SECRET_ARN == aws_secretsmanager_secret.thundermail.arn && length(aws_bedrockagentcore_gateway_target.thundermail.target_configuration[0].mcp[0].lambda[0].tool_schema[0].inline_payload) == 3
    error_message = "Native single ARM64 Lambda and inline three tools, not HTTP."
  }
  assert {
    condition     = toset(jsondecode(aws_ecr_repository_policy.tools_images.policy).Statement[0].Condition.ArnLike["aws:SourceArn"]) == toset([local.microsoft365_function_arn, local.thundermail_function_arn])
    error_message = "Extend existing shared pull grant only by the exact Thundermail ARN."
  }
}
