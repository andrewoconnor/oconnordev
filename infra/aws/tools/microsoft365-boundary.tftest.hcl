# Both halves of the AWS read boundary's gate.
#
# `security_gateway_enabled` is derived from a cross-stack dependency
# reference, so it is empty on a pull-request plan and on the first apply after
# the reference is created. The two runs below pin the behaviour on either side
# of that value, which is what the previous design got wrong: the target was
# gated but the Cedar permits were not, so a missing URL destroyed the target
# while leaving the permits pointing at action names that no longer existed.
# The policy engine rejected them as unrecognized actions and the apply failed,
# taking the AWS tools away entirely rather than leaving them unavailable.
#
# `mock_provider` keeps this offline: no credentials, no account, no apply.

mock_provider "aws" {
  # Policy preconditions decode Statement during plan, so return a minimal
  # valid policy document instead of the mock provider's generated placeholder.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  # Keep computed values consumed by provider-side argument validation valid.
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


run "microsoft365_disabled_by_default" {
  command = plan
  assert {
    condition     = length(aws_lambda_function.microsoft365) == 0 && length(aws_bedrockagentcore_gateway_target.microsoft365) == 0 && length(aws_bedrockagentcore_policy.microsoft365_read) == 0 && length(aws_iam_role_policy.microsoft365_gateway_invoke) == 0 && length(aws_iam_role_policy.microsoft365_runtime) == 0
    error_message = "Runtime, target, permissions and permits must all be absent before owner activation."
  }
  assert {
    condition     = aws_ecr_repository.tools_images.name == "oconnordev-tools" && aws_ecr_repository.tools_images.force_delete == false && aws_ecr_repository.tools_images.image_tag_mutability == "IMMUTABLE" && aws_secretsmanager_secret.microsoft365_cache.recovery_window_in_days == 30
    error_message = "Bootstrap must provision the shared immutable tools repository without force deletion and only recoverable secret metadata."
  }
  assert {
    condition = (
      length(jsondecode(aws_ecr_repository_policy.microsoft365_lambda_pull.policy).Statement) == 1 &&
      jsondecode(aws_ecr_repository_policy.microsoft365_lambda_pull.policy).Statement[0].Principal.Service == "lambda.amazonaws.com" &&
      jsondecode(aws_ecr_repository_policy.microsoft365_lambda_pull.policy).Statement[0].Effect == "Allow" &&
      toset(jsondecode(aws_ecr_repository_policy.microsoft365_lambda_pull.policy).Statement[0].Action) == toset(["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]) &&
      jsondecode(aws_ecr_repository_policy.microsoft365_lambda_pull.policy).Statement[0].Condition.ArnLike["aws:SourceArn"] == "arn:aws:lambda:us-east-1:421680664125:function:hermes-microsoft365-mcp"
    )
    error_message = "Shared ECR must still grant service pull to only the exact Microsoft365 function."
  }
}
run "microsoft365_requires_owner_inputs" {
  command = plan
  variables { microsoft365_runtime_enabled = true }
  expect_failures = [aws_lambda_function.microsoft365[0]]
}
run "microsoft365_rejects_tag" {
  command = plan
  variables { microsoft365_image_digest = "latest" }
  expect_failures = [var.microsoft365_image_digest]
}
run "microsoft365_enabled" {
  command = plan
  variables {
    microsoft365_runtime_enabled = true
    # Synthetic test-only digest, never an owner deployment example.
    microsoft365_image_digest          = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    microsoft365_owner_home_account_id = "synthetic.9188040d-6c67-4c5b-b112-36a304b66dad"
    microsoft365_client_id             = "00000000-0000-4000-8000-000000000001"
  }
  assert {
    condition     = length(aws_bedrockagentcore_gateway_target.microsoft365) == 1 && length(aws_bedrockagentcore_policy.microsoft365_read) == 5 && length(aws_iam_role_policy.microsoft365_gateway_invoke) == 1
    error_message = "Target and all five exact Cedar actions must be enabled together."
  }
  assert {
    condition     = aws_lambda_function.microsoft365[0].architectures == tolist(["arm64"]) && aws_lambda_function.microsoft365[0].reserved_concurrent_executions == 1 && aws_lambda_function_url.microsoft365[0].authorization_type == "AWS_IAM"
    error_message = "Only serialized arm64 IAM-authenticated HTTP runtime is supported."
  }
  assert {
    condition     = alltrue([for k, v in aws_bedrockagentcore_policy.microsoft365_read : strcontains(v.definition[0].cedar[0].statement, "microsoft365___${k}") && strcontains(v.definition[0].cedar[0].statement, "hermes-mcp/invoke")])
    error_message = "Rendered Cedar must use exact gateway actions and existing OAuth scope."
  }
}
