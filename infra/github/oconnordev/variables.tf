variable "oconnordev_site_deploy_role_arn" {
  description = "Deploy role ARN exported by the PRODUCTION Spacelift stack."
  type        = string

  validation {
    condition     = length(trimspace(var.oconnordev_site_deploy_role_arn)) > 0
    error_message = "The PRODUCTION dependency must provide a non-empty site deploy role ARN."
  }
}

variable "oconnordev_cloudfront_distribution_id" {
  description = "CloudFront distribution ID exported by the PRODUCTION Spacelift stack."
  type        = string

  validation {
    condition     = length(trimspace(var.oconnordev_cloudfront_distribution_id)) > 0
    error_message = "The PRODUCTION dependency must provide a non-empty CloudFront distribution ID."
  }
}

variable "oconnordev_tools_github_actions_broker_role_arn" {
  description = "TOOLS stack output for the GitHub Actions OIDC broker role ARN. The default is the fixed TOOLS account ARN so speculative plans can run before the dependency reference is applied."
  type        = string
  default     = "arn:aws:iam::421680664125:role/oconnordev-github-actions-broker"

  validation {
    condition     = var.oconnordev_tools_github_actions_broker_role_arn == "arn:aws:iam::421680664125:role/oconnordev-github-actions-broker"
    error_message = "The GitHub Actions broker must be the exact oconnordev-github-actions-broker role in TOOLS account 421680664125."
  }
}

variable "github_app_id" {
  description = "Existing GitHub App ID supplied by the dedicated Spacelift auth context."
  type        = string
}

variable "github_app_installation_id" {
  description = "GitHub App installation ID for andrewoconnor/oconnordev, supplied by the dedicated Spacelift auth context."
  type        = string
}

variable "github_app_private_key" {
  description = "Existing GitHub App private key from the dedicated Spacelift secret context."
  type        = string
  sensitive   = true
  ephemeral   = true
}
