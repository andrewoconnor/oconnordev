data "aws_secretsmanager_secret" "github_machine_user_pat_existing" {
  name = "/hermes/github/machine-user-pat"
}

resource "aws_secretsmanager_secret" "github_machine_user_pat" {
  # checkov:skip=CKV_AWS_149:Adopted existing secret. It keeps whatever key the existing secret already uses (kms_key_id is read back from the data source and preserved). A customer-managed key would have to be created in the TOOLS AWS account and its policy would have to grant both the AgentCore credential provider's execution role and whoever rotates the value; a key policy wrong in either direction fails the credential read at request time rather than loudly at apply.
  # checkov:skip=CKV2_AWS_57:Automatic rotation would need a Lambda that can mint a replacement fine-grained GitHub PAT. A PAT cannot be rotated programmatically without a GitHub App or a token-minting service, so the rotation function would have nothing to call; the value is rotated by hand by the repository owner.
  name        = data.aws_secretsmanager_secret.github_machine_user_pat_existing.name
  description = data.aws_secretsmanager_secret.github_machine_user_pat_existing.description
  kms_key_id  = trimspace(data.aws_secretsmanager_secret.github_machine_user_pat_existing.kms_key_id) != "" ? data.aws_secretsmanager_secret.github_machine_user_pat_existing.kms_key_id : null

  lifecycle {
    prevent_destroy = true
  }
}

variable "hermes_github_allowed_repositories" {
  description = "AWS-side allowlist of repository names owned by andrewoconnor. Empty denies all access."
  type        = set(string)
  default     = ["oconnordev"]

  validation {
    condition = alltrue([
      for repository in var.hermes_github_allowed_repositories : can(regex("^[A-Za-z0-9_.-]{1,100}$", repository)) && !startswith(repository, ".") && !endswith(repository, ".git")
    ])
    error_message = "Allowed repository entries must be repository names only (no owner, slash, or URL)."
  }
}

variable "hermes_github_default_branches" {
  description = "Configured default branch for each allowlisted repository; writes and PR bases are constrained against these values."
  type        = map(string)
  default     = { oconnordev = "master" }

  validation {
    condition = alltrue([
      for repository in keys(var.hermes_github_default_branches) : contains(var.hermes_github_allowed_repositories, repository)
    ])
    error_message = "Default-branch map keys must be present in hermes_github_allowed_repositories."
  }

  validation {
    condition = alltrue([
      for repository in var.hermes_github_allowed_repositories : contains(keys(var.hermes_github_default_branches), repository)
    ])
    error_message = "Set a configured default branch for every allowlisted repository before enabling writes."
  }

  validation {
    condition = alltrue([
      for branch in values(var.hermes_github_default_branches) : can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$", branch)) && !strcontains(branch, "..") && !strcontains(branch, "//") && !endswith(branch, "/")
    ])
    error_message = "Default branch values must be valid, non-empty Git branch names."
  }
}

variable "hermes_github_machine_user_pat_json_key" {
  description = "JSON object key holding the GitHub PAT in the existing Secrets Manager secret. AgentCore EXTERNAL credential providers require SecretString to be a JSON object (for example, {\"api_key\":\"<PAT>\"}); plaintext SecretString is rejected. Terraform never reads or manages the value."
  type        = string
  default     = "api_key"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{1,64}$", var.hermes_github_machine_user_pat_json_key))
    error_message = "hermes_github_machine_user_pat_json_key must be a non-empty JSON key name."
  }
}

locals {
  github_target_name   = "github"
  github_tool_manifest = jsondecode(file("${local.adapter_root}/github-mcp-tools.json"))
  github_native_tools  = toset(local.github_tool_manifest.tools)
  github_read_tools    = toset(["get_file_contents", "list_branches", "get_commit", "pull_request_read", "get_job_logs"])
  github_branch_tools  = toset(["create_branch", "push_files", "delete_file"])
  github_branch_tool_clauses = {
    push_files  = "context.input has files && !context.input.files.isEmpty() &&"
    delete_file = "context.input has path && context.input.path != \"\" &&"
  }
  github_policy_tools   = setunion(local.github_read_tools, local.github_branch_tools, toset(["create_pull_request"]))
  github_cedar_repo_set = jsonencode(sort(tolist(var.hermes_github_allowed_repositories)))

  github_branch_policy_matrix = {
    for pair in setproduct(var.hermes_github_allowed_repositories, local.github_branch_tools) : jsonencode(pair) => {
      repository     = pair[0]
      tool           = pair[1]
      default_branch = var.hermes_github_default_branches[pair[0]]
    }
  }
}

resource "aws_bedrockagentcore_api_key_credential_provider" "github" {
  name                  = "hermes-github-machine-user-pat"
  api_key_secret_source = "EXTERNAL"

  api_key_secret_config {
    secret_id = aws_secretsmanager_secret.github_machine_user_pat.arn
    json_key  = var.hermes_github_machine_user_pat_json_key
  }
}

data "aws_iam_policy_document" "github_target_credentials" {
  statement {
    sid     = "GetGitHubPATFromAgentCoreIdentity"
    effect  = "Allow"
    actions = ["bedrock-agentcore:GetResourceApiKey"]

    resources = [
      aws_bedrockagentcore_api_key_credential_provider.github.credential_provider_arn,
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:token-vault/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
      "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default/workload-identity/${local.hermes_gateway_name}-*",
    ]
  }

  statement {
    sid       = "ReadOnlyGitHubPATSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.github_machine_user_pat.arn]
  }
}

resource "aws_iam_role_policy" "github_target_credentials" {
  name   = "hermes-github-agentcore-credentials"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.github_target_credentials.json
}

resource "terraform_data" "github_target_catalog_rebuild" {
  # AWS provider 6.66.0 exposes no explicit catalog-refresh argument for an
  # MCP server target. DEFAULT listings are cached by AgentCore, so replace the
  # target when its relevant upstream manifest inputs change.
  triggers_replace = [sha256(jsonencode({
    endpoint = local.github_tool_manifest.hosted_endpoint
    tools    = sort(tolist(local.github_native_tools))
  }))]
}

resource "aws_bedrockagentcore_gateway_target" "github" {
  name               = local.github_target_name
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Direct, dynamically listed target to GitHub's official hosted MCP server."

  credential_provider_configuration {
    api_key {
      provider_arn              = aws_bedrockagentcore_api_key_credential_provider.github.credential_provider_arn
      credential_location       = "HEADER"
      credential_parameter_name = "Authorization"
      credential_prefix         = "Bearer"
    }
  }

  target_configuration {
    mcp {
      mcp_server {
        endpoint     = local.github_tool_manifest.hosted_endpoint
        listing_mode = "DEFAULT"
      }
    }
  }

  metadata_configuration {
    allowed_request_headers = ["x-mcp-tools"]
  }

  lifecycle {
    precondition {
      condition     = length(setsubtract(local.github_policy_tools, local.github_native_tools)) == 0 && length(local.github_native_tools) == length(local.github_policy_tools)
      error_message = "The GitHub MCP manifest must contain exactly the tool names covered by the Cedar policies."
    }

    replace_triggered_by = [terraform_data.github_target_catalog_rebuild]
  }

  depends_on = [
    aws_iam_role_policy.hermes_gateway_core,
    aws_iam_role_policy.github_target_credentials,
    aws_iam_role_policy.hermes_gateway_policy_authorization,
  ]
}