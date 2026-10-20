locals {
  gateway_workload_identity_name = "hermes-rfltsq6ysk"
}

import {
  for_each = var.spacelift_run_id == "terraform-test" ? toset([]) : toset([local.gateway_workload_identity_name])
  to       = aws_bedrockagentcore_workload_identity.gateway
  id       = each.value
}

resource "aws_bedrockagentcore_workload_identity" "gateway" {
  name                                = local.gateway_workload_identity_name
  allowed_resource_oauth2_return_urls = [local.oauth_return_url, local.oauth_callback_return_url]

  lifecycle {
    precondition {
      condition     = try(endswith(aws_bedrockagentcore_gateway.hermes.workload_identity_details[0].workload_identity_arn, "/${local.gateway_workload_identity_name}"), true)
      error_message = "gateway_workload_identity_name must be the workload identity that AgentCore created for the hermes gateway."
    }
  }
}
