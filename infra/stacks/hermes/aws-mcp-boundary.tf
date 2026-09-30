variable "hermes_aws_mcp_endpoint" {
  description = "AWS MCP Server endpoint fronted by the shared gateway target."
  type        = string
  default     = "https://aws-mcp.us-east-1.api.aws/mcp"

  validation {
    condition     = can(regex("^https://aws-mcp\\.[a-z0-9-]+\\.api\\.aws/mcp$", var.hermes_aws_mcp_endpoint))
    error_message = "hermes_aws_mcp_endpoint must be an https AWS MCP Server endpoint of the form https://aws-mcp.<region>.api.aws/mcp."
  }
}

variable "hermes_aws_mcp_sigv4_service" {
  description = "SigV4 service name the gateway uses to sign requests to the AWS MCP Server. The MCP proxy for AWS infers this from the endpoint hostname; it is pinned here so the signature cannot silently follow a changed endpoint."
  type        = string
  default     = "aws-mcp"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,63}$", var.hermes_aws_mcp_sigv4_service))
    error_message = "hermes_aws_mcp_sigv4_service must be a lowercase AWS service name."
  }
}

locals {
  hermes_aws_target_name  = "aws"
  aws_tool_manifest       = jsondecode(file("${path.module}/adapter/aws-mcp-tools.json"))
  aws_native_tools        = toset(local.aws_tool_manifest.tools)
  hermes_aws_readonly_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/ReadOnlyAccess"
}

# The gateway signs requests to the AWS MCP Server with its own role, so the
# role's IAM permissions are the real read/write boundary. The AWS MCP Server
# executes whatever the caller is allowed to execute; it is not itself a
# read-only service, so attaching a read-only policy is what makes this
# boundary read-only.
resource "aws_iam_role_policy_attachment" "hermes_gateway_readonly" {
  role       = aws_iam_role.hermes_gateway.name
  policy_arn = local.hermes_aws_readonly_arn
}

# Defence in depth: AWS's managed ReadOnlyAccess already covers a very wide set
# of reads. Secret *values* are deliberately outside this boundary, and the
# GitHub PAT secret is carved out because the gateway needs it for the API-key
# credential provider. An explicit Deny always wins over the managed allow.
data "aws_iam_policy_document" "hermes_gateway_readonly_guardrails" {
  statement {
    sid     = "DenySecretValueReadsOutsideGitHubPat"
    effect  = "Deny"
    actions = ["secretsmanager:GetSecretValue"]

    # NotResource only. An IAM statement may carry either Resource or
    # NotResource but never both, and aws_iam_policy_document emits whichever
    # ones are set: adding `resources = ["*"]` here produces a statement with
    # both keys, which the IAM API rejects with MalformedPolicyDocument. No
    # local gate catches it, because the document is computed locally and only
    # the IAM API validates it, hence the precondition on the resource below.
    # Keep the GitHub machine-user PAT readable: the GitHub target's API-key
    # credential provider resolves it through this role, so denying it here
    # would break the sibling target.
    not_resources = [aws_secretsmanager_secret.github_machine_user_pat.arn]
  }
}

resource "aws_iam_role_policy" "hermes_gateway_readonly_guardrails" {
  name   = "hermes-agentcore-readonly-guardrails"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.hermes_gateway_readonly_guardrails.json

  lifecycle {
    # Guards the failure mode that tofu validate, tflint and Checkov cannot
    # see: a statement carrying both Resource and NotResource.
    precondition {
      condition = length([
        for statement in jsondecode(data.aws_iam_policy_document.hermes_gateway_readonly_guardrails.json).Statement :
        statement if can(statement.Resource) && can(statement.NotResource)
      ]) == 0
      error_message = "Each guardrail statement must set either Resource or NotResource, never both; the IAM API rejects a statement that sets both."
    }
  }
}

resource "aws_bedrockagentcore_gateway_target" "aws" {
  name               = local.hermes_aws_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Read-only AWS access through AWS's managed MCP Server, signed with the gateway role."

  # MCP server targets use SigV4, not an API key or OAuth token, so the gateway
  # signs outbound requests with its own service role.
  credential_provider_configuration {
    gateway_iam_role {
      service = var.hermes_aws_mcp_sigv4_service
      region  = data.aws_region.current.region
    }
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint = var.hermes_aws_mcp_endpoint
        # An AgentCore policy engine cannot enumerate a DYNAMIC target live, so
        # tools are synced at target create/update time instead.
        listing_mode = "DEFAULT"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = length(local.aws_native_tools) == 7
      error_message = "The AWS MCP manifest must contain exactly the seven tool names covered by the Cedar policies and the Hermes adapter allowlist."
    }
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.hermes_gateway_readonly_guardrails,
    aws_iam_role_policy_attachment.hermes_gateway_readonly,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}

# One permit per manifest tool. There is no repository or owner dimension to
# constrain here: the inbound Cognito client is the only caller, and the
# read-only guarantee comes from the gateway role's IAM policy above.
resource "aws_bedrockagentcore_policy" "aws_tool" {
  for_each = local.aws_native_tools

  name             = "HermesAWS${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Permit the read-only AWS MCP tool ${each.key}."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal,
          action == AgentCore::Action::"${local.hermes_aws_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        );
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.aws]
}

output "hermes_aws_mcp_endpoint" {
  description = "AWS MCP Server endpoint fronted by the shared gateway."
  value       = var.hermes_aws_mcp_endpoint
}

output "hermes_aws_mcp_target_name" {
  description = "Gateway target name that prefixes the AWS MCP tools."
  value       = local.hermes_aws_target_name
}