locals {
  drumrollworld_deployment_configured = (
    length(trimspace(var.drumrollworld_site_deploy_role_arn)) > 0 &&
    length(trimspace(var.drumrollworld_cloudfront_distribution_id)) > 0
  )
}

resource "github_actions_variable" "drumrollworld_site_deploy_role_arn" {
  count = local.drumrollworld_deployment_configured ? 1 : 0

  repository    = "oconnordev"
  variable_name = "DRUMROLLWORLD_SITE_DEPLOY_ROLE_ARN"
  value         = var.drumrollworld_site_deploy_role_arn
}

resource "github_actions_variable" "drumrollworld_cloudfront_distribution_id" {
  count = local.drumrollworld_deployment_configured ? 1 : 0

  repository    = "oconnordev"
  variable_name = "DRUMROLLWORLD_CLOUDFRONT_DISTRIBUTION_ID"
  value         = var.drumrollworld_cloudfront_distribution_id
}

variable "drumrollworld_site_deploy_role_arn" {
  description = "DrumrollWorld stack deploy role output. Empty until the workload and dependency have applied."
  type        = string
  default     = ""

  validation {
    condition     = var.drumrollworld_site_deploy_role_arn == "" || can(regex("^arn:aws:iam::[0-9]{12}:role/drumrollworld-site-deploy$", var.drumrollworld_site_deploy_role_arn))
    error_message = "Supply the DrumrollWorld deploy role ARN, or leave it empty before bootstrap."
  }
}

variable "drumrollworld_cloudfront_distribution_id" {
  description = "DrumrollWorld stack distribution output. Empty until the workload and dependency have applied."
  type        = string
  default     = ""

  validation {
    condition     = var.drumrollworld_cloudfront_distribution_id == "" || can(regex("^[A-Z0-9]+$", var.drumrollworld_cloudfront_distribution_id))
    error_message = "Supply a CloudFront distribution ID, or leave it empty before bootstrap."
  }
}
