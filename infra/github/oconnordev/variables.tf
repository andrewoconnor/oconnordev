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
