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
  # This suite isolates the pre-existing AWS/GitHub boundary, not mail activation.
  spacelift_run_id = "terraform-test"
  # Offline gateway fixture: explicit binding, not a claim of a live mock schema.
  github_ruleset_cedar_schema = {
    gateway_arn        = "arn:aws:bedrock-agentcore:us-east-1:421680664125:gateway/hermes-mock"
    level_entity_type  = "AgentCore::ID_8d56337199_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_level"
    method_entity_type = "AgentCore::ID_e312b33e9c_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_method"
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

run "github_settings_reads_are_repository_scoped" {
  command = plan

  assert {
    condition = alltrue([
      for tool in ["repository_ruleset_read", "list_repository_collaborators", "list_label", "get_label"] :
      contains(local.github_native_tools, tool) && contains(local.github_read_tools, tool) &&
      contains(keys(aws_bedrockagentcore_policy.github_read), tool) && !contains(local.github_branch_tools, tool)
    ])
    error_message = "Every native settings read must have a read permit and no branch-write permit."
  }

  assert {
    condition     = local.github_native_tools == local.github_policy_tools && length(local.github_read_tools) == 9
    error_message = "The manifest and Cedar policy tools must match exactly with nine reads."
  }

  assert {
    condition = (
      strcontains(local.github_read_tool_clauses.repository_ruleset_read, "${var.github_ruleset_cedar_schema.level_entity_type}::\"repository\"") &&
      strcontains(local.github_read_tool_clauses.repository_ruleset_read, "${var.github_ruleset_cedar_schema.method_entity_type}::\"list\"") &&
      strcontains(local.github_read_tool_clauses.repository_ruleset_read, "${var.github_ruleset_cedar_schema.method_entity_type}::\"get\"")
    )
    error_message = "Ruleset policy must render the explicit observed EntityUID type IDs, not strings or generated types."
  }

  assert {
    condition     = aws_bedrockagentcore_api_key_credential_provider.github.api_key_secret_source == "EXTERNAL"
    error_message = "The existing EXTERNAL credential chain must remain unchanged."
  }
}

run "github_empty_allowlist_denies_all_reads" {
  command = plan

  variables {
    hermes_github_allowed_repositories = []
    hermes_github_default_branches     = {}
  }

  assert {
    condition     = length(aws_bedrockagentcore_policy.github_read) == 0 && length(aws_bedrockagentcore_policy.github_branch_write) == 0 && length(aws_bedrockagentcore_policy.github_create_draft_pr) == 0
    error_message = "An empty repository allowlist must create no GitHub permits."
  }
}

run "ruleset_observed_schema_binding_rejects_another_gateway" {
  command = plan

  # Known plan-time gateway value so this exercises the resource precondition.
  override_resource {
    target = aws_bedrockagentcore_gateway.hermes
    values = {
      gateway_arn = "arn:aws:bedrock-agentcore:us-east-1:421680664125:gateway/another"
      gateway_id  = "another"
    }
  }

  variables {
    github_ruleset_cedar_schema = {
      gateway_arn        = "arn:aws:bedrock-agentcore:us-east-1:421680664125:gateway/hermes-rfltsq6ysk"
      level_entity_type  = "AgentCore::ID_8d56337199_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_level"
      method_entity_type = "AgentCore::ID_e312b33e9c_arnawsbedrockagentcoreuseast1421680664125gatewayhermesrfltsq6ysk___github___repository_ruleset_read_Input_method"
    }
  }

  expect_failures = [aws_bedrockagentcore_policy.github_read["repository_ruleset_read"]]
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
    condition     = terraform_data.github_target_catalog_rebuild.triggers_replace == [sha256(jsonencode({ endpoint = local.github_tool_manifest.hosted_endpoint, tools = sort(tolist(local.github_native_tools)) }))]
    error_message = "The GitHub cached tool catalog must be replaced whenever the endpoint or manifest tool names change."
  }

  assert {
    condition     = terraform_data.github_target_catalog_rebuild.triggers_replace[0] != sha256(jsonencode({ endpoint = local.github_tool_manifest.hosted_endpoint, tools = sort(tolist(setunion(local.github_native_tools, toset(["__synthetic_manifest_change__"])))) }))
    error_message = "Adding a GitHub manifest tool must change the target catalog replacement trigger."
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
run "google_is_read_only_user_delegated_oauth" {
  command = plan

  assert {
    condition     = aws_bedrockagentcore_gateway_target.google.credential_provider_configuration[0].oauth[0].grant_type == "AUTHORIZATION_CODE" && aws_bedrockagentcore_gateway_target.google.credential_provider_configuration[0].oauth[0].scopes == toset(["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/gmail.readonly"])
    error_message = "Google must use user-delegated OAuth with only the read-only Calendar and Gmail scopes."
  }

  assert {
    condition     = aws_bedrockagentcore_oauth2_credential_provider.google.oauth2_provider_config[0].google_oauth2_provider_config[0].client_secret_source == "EXTERNAL"
    error_message = "The Google provider must read its client secret from Secrets Manager, never from state."
  }

  assert {
    condition     = length(aws_bedrockagentcore_policy.google_read) == 5 && alltrue([for k, v in aws_bedrockagentcore_policy.google_read : strcontains(v.definition[0].cedar[0].statement, "google___${k}")])
    error_message = "Each Google tool needs exactly one scoped Cedar permit."
  }

  assert {
    condition     = contains(local.hermes_gateway_readable_secret_arns, data.aws_secretsmanager_secret.google_oauth_client.arn)
    error_message = "The gateway guardrail must allow reading only the named Google client secret."
  }
}

run "outlook_is_read_only_oauth_with_kms_client_assertion" {
  command = plan

  assert {
    condition     = aws_bedrockagentcore_gateway_target.outlook.credential_provider_configuration[0].oauth[0].grant_type == "AUTHORIZATION_CODE" && aws_bedrockagentcore_gateway_target.outlook.credential_provider_configuration[0].oauth[0].scopes == toset(["https://graph.microsoft.com/Calendars.Read", "https://graph.microsoft.com/Mail.Read", "offline_access"])
    error_message = "Outlook must use user-delegated OAuth with only read-only mail and calendar scopes."
  }

  assert {
    condition     = aws_bedrockagentcore_oauth2_credential_provider.outlook.oauth2_provider_config[0].custom_oauth2_provider_config[0].client_authentication_method == "PRIVATE_KEY_JWT" && aws_bedrockagentcore_oauth2_credential_provider.outlook.oauth2_provider_config[0].custom_oauth2_provider_config[0].private_key_jwt_config[0].signing_algorithm == "PS256"
    error_message = "The Outlook provider must authenticate with a KMS-signed PS256 client assertion, not a client secret."
  }

  assert {
    condition     = length(aws_bedrockagentcore_policy.outlook_read) == 5 && alltrue([for k, v in aws_bedrockagentcore_policy.outlook_read : strcontains(v.definition[0].cedar[0].statement, "outlook___${k}")])
    error_message = "Each Outlook tool needs exactly one scoped Cedar permit."
  }

  assert {
    condition     = aws_kms_key.outlook_signing.key_usage == "SIGN_VERIFY" && aws_kms_key.outlook_signing.customer_master_key_spec == "RSA_2048"
    error_message = "The Outlook signing key must be an RSA signing key."
  }
}

run "schwab_is_read_only_oauth_with_hosted_consent" {
  command = plan

  assert {
    condition     = aws_bedrockagentcore_gateway_target.schwab.credential_provider_configuration[0].oauth[0].grant_type == "AUTHORIZATION_CODE" && aws_bedrockagentcore_gateway_target.schwab.credential_provider_configuration[0].oauth[0].default_return_url == "${aws_lambda_function_url.oauth_callback.function_url}callback"
    error_message = "Schwab must use user-delegated OAuth that returns to the hosted consent callback."
  }

  assert {
    condition     = length(aws_bedrockagentcore_policy.schwab_read) == 7 && !anytrue([for path in keys(local.schwab_openapi.paths) : strcontains(path, "orders")])
    error_message = "Schwab exposes seven read-only tools and no order endpoint."
  }

  assert {
    condition     = aws_lambda_function_url.oauth_callback.authorization_type == "NONE" && aws_lambda_permission.oauth_callback_url.function_url_auth_type == "NONE" && aws_lambda_permission.oauth_callback_invoke.invoked_via_function_url
    error_message = "The consent callback must be reachable by a browser redirect, and only through its Function URL."
  }

  assert {
    condition     = contains(local.hermes_gateway_readable_secret_arns, data.aws_secretsmanager_secret.schwab_oauth_client.arn)
    error_message = "The gateway guardrail must allow reading the named Schwab client secret."
  }

  assert {
    condition     = contains(aws_bedrockagentcore_workload_identity.gateway.allowed_resource_oauth2_return_urls, "${aws_lambda_function_url.oauth_callback.function_url}callback") && contains(aws_bedrockagentcore_workload_identity.gateway.allowed_resource_oauth2_return_urls, "http://localhost:9090/oauth2/callback")
    error_message = "The gateway workload identity must allow both the hosted and the local consent return URLs."
  }
}
