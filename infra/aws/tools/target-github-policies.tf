resource "aws_bedrockagentcore_policy" "github_read" {
  for_each = length(var.hermes_github_allowed_repositories) == 0 ? toset([]) : local.github_read_tools

  name             = "HermesGitHubRead_${replace(each.key, "_", "")}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Read-only ${each.key} is limited to the configured owner and repository allowlist."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal,
          action == AgentCore::Action::"${local.github_target_name}___${each.key}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          context.input has owner &&
          context.input.owner == "andrewoconnor" &&
          context.input has repo &&
          ${local.github_cedar_repo_set}.contains(context.input.repo)${lookup(local.github_read_tool_clauses, each.key, "")}
        };
      CEDAR
    }
  }

  lifecycle {
    precondition {
      condition = each.key != "repository_ruleset_read" ? true : (
        var.github_ruleset_cedar_schema.gateway_arn == aws_bedrockagentcore_gateway.hermes.gateway_arn
      )
      error_message = "Ruleset Cedar enum types are bound to a different gateway. Supply independently observed github_ruleset_cedar_schema inputs for this gateway."
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.github]
}

resource "aws_bedrockagentcore_policy" "github_branch_write" {
  for_each = local.github_branch_policy_matrix

  name             = "HermesGitHubWrite${replace(each.value.tool, "_", "")}${substr(sha256(each.value.repository), 0, 8)}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Allow ${each.value.tool} only on hermes/ feature branches in ${each.value.repository}."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal,
          action == AgentCore::Action::"${local.github_target_name}___${each.value.tool}",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          context.input has owner &&
          context.input.owner == "andrewoconnor" &&
          context.input has repo &&
          context.input.repo == ${jsonencode(each.value.repository)} &&
          ${lookup(local.github_branch_tool_clauses, each.value.tool, "")}
          context.input has branch &&
          context.input.branch like "hermes/*" &&
          context.input.branch != "hermes/" &&
          context.input.branch != ${jsonencode(each.value.default_branch)}
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.github]
}

resource "aws_bedrockagentcore_policy" "github_create_draft_pr" {
  for_each = {
    for repository, branch in var.hermes_github_default_branches : repository => branch
    if contains(var.hermes_github_allowed_repositories, repository)
  }

  name             = "HermesGitHubDraftPR${substr(sha256(each.key), 0, 12)}"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Allow draft PR creation for ${each.key} only against its configured default branch."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal,
          action == AgentCore::Action::"${local.github_target_name}___create_pull_request",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          context.input has owner &&
          context.input.owner == "andrewoconnor" &&
          context.input has repo &&
          context.input.repo == ${jsonencode(each.key)} &&
          context.input has head &&
          ((context.input.head like "hermes/*" && context.input.head != "hermes/") ||
           (context.input.head like "andrewoconnor:hermes/*" && context.input.head != "andrewoconnor:hermes/")) &&
          context.input.head != ${jsonencode(each.value)} &&
          context.input has base &&
          context.input.base == ${jsonencode(each.value)} &&
          context.input has draft &&
          context.input.draft == true &&
          !(context.input has maintainer_can_modify && context.input.maintainer_can_modify != false) &&
          !(context.input has reviewers && !context.input.reviewers.isEmpty())
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.github]
}
