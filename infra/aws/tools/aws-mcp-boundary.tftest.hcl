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
}

run "knowledge_target_exposes_all_read_only_tools" {
  command = plan

  assert {
    condition     = aws_bedrockagentcore_gateway_target.knowledge.name == "knowledge" && local.knowledge_endpoint == "https://knowledge-mcp.global.api.aws"
    error_message = "The public AWS Knowledge MCP endpoint must be configured as the knowledge target."
  }

  assert {
    condition     = length(aws_bedrockagentcore_policy.knowledge_tool) == 5
    error_message = "Cedar must permit all five currently advertised read-only AWS Knowledge tools."
  }

  assert {
    condition = (
      length(setsubtract(local.knowledge_native_tools, local.knowledge_read_only_tools)) == 0 &&
      length(setsubtract(local.knowledge_read_only_tools, local.knowledge_native_tools)) == 0
    )
    error_message = "The target manifest must include exactly the complete read-only AWS Knowledge tool catalog."
  }

  assert {
    condition     = "${local.knowledge_target_name}___aws___list_regions" == "knowledge___aws___list_regions"
    error_message = "Cedar actions must include the target prefix and the upstream AWS namespace."
  }
}

run "disabled_when_the_security_gateway_is_unresolved" {
  command = plan

  variables {
    security_gateway_url = ""
    security_gateway_arn = ""
  }

  # No target, so nothing advertises the AWS actions...
  assert {
    condition     = length(aws_bedrockagentcore_gateway_target.aws) == 0
    error_message = "The AWS target must not exist while the security gateway URL is unresolved."
  }

  # ...and therefore no permit may name them.
  assert {
    condition     = length(aws_bedrockagentcore_policy.aws_tool) == 0
    error_message = "Cedar permits must not exist without the target that advertises their actions."
  }

  # ...and nothing may claim a permission to invoke a gateway that is not known.
  assert {
    condition     = length(aws_iam_role_policy.hermes_gateway_security_gateway) == 0
    error_message = "The invoke permission must not exist while there is no gateway to invoke."
  }

  # The target name is still exported, because the adapter's manifest is what
  # defines it and the name does not depend on the URL.
  assert {
    condition     = output.hermes_aws_mcp_target_name == "aws"
    error_message = "The AWS target name is a constant and must not depend on the gate."
  }
}

run "enabled_when_the_security_gateway_is_resolved" {
  command = plan

  variables {
    security_gateway_url = "https://oconnordev-security.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
    security_gateway_arn = "arn:aws:bedrock-agentcore:us-east-1:482921124454:gateway/oconnordev-security"
  }

  assert {
    condition     = length(aws_bedrockagentcore_gateway_target.aws) == 1
    error_message = "The AWS target must exist once the security gateway URL resolves."
  }

  # One permit per manifest tool, and the manifest is the single source of truth
  # for both the count and the names.
  assert {
    condition     = length(aws_bedrockagentcore_policy.aws_tool) == 7
    error_message = "All seven AWS Cedar permits must exist alongside the target."
  }

  assert {
    condition     = length(aws_iam_role_policy.hermes_gateway_security_gateway) == 1
    error_message = "The invoke permission must exist once there is a gateway to invoke."
  }

  # The permit has to name the wire action, not the client-visible name: the
  # gateway advertises aws___aws___aws___<tool> because the server namespaces
  # with aws___ and each of the two gateways adds a target prefix. A mocked plan
  # cannot read back the rendered policy body, so this asserts the two inputs
  # the resource concatenates, which are what fix the action name. The rendered
  # body is proven against the live gateway by the adapter's smoke test.
  assert {
    condition     = "${local.hermes_aws_action_prefix}aws___list_regions" == "aws___aws___aws___list_regions"
    error_message = "The manifest's wire prefix plus the canonical tool name must be the three-level action the gateway advertises."
  }

  # ...while the tool the manifest declares stays canonical, which is what the
  # adapter exposes to the client.
  assert {
    condition     = contains(local.aws_native_tools, "aws___list_regions")
    error_message = "The manifest must keep the canonical aws___<tool> names the client sees."
  }

  assert {
    condition     = local.hermes_aws_action_prefix == "aws___aws___"
    error_message = "The wire prefix must come from the manifest's gateway_action_prefix."
  }

  assert {
    condition     = contains(local.github_native_tools, "get_job_logs") && contains(local.github_read_tools, "get_job_logs") && !contains(local.github_branch_tools, "get_job_logs")
    error_message = "GitHub job logs must be in the manifest and read-only Cedar tool set, never the branch-write set."
  }

  assert {
    condition     = contains(keys(aws_bedrockagentcore_policy.github_read), "get_job_logs")
    error_message = "The GitHub job-logs tool must receive a repository-scoped read policy."
  }

  assert {
    condition     = "${local.github_target_name}___get_job_logs" == "github___get_job_logs"
    error_message = "The Cedar read policy must name the GitHub target action exactly."
  }
}
