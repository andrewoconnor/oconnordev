variable "name" { type = string }
variable "domain_name" { type = string }
variable "bucket_name" { type = string }
variable "origin_id" { type = string }
variable "zone_id" { type = string }
variable "broker_role_arn" { type = string }
variable "content_security_policy" { type = string }
variable "error_responses" {
  type = list(object({
    error_code            = number
    response_code         = number
    response_page_path    = string
    error_caching_min_ttl = number
  }))
  default = []
}
variable "extra_deploy_statements" {
  type = list(object({
    sid             = string
    effect          = string
    actions         = list(string)
    object_suffixes = list(string)
  }))
  default = []
}
variable "existing_certificate_arn" {
  description = "Reuse a shared wildcard certificate instead of creating a competing owner. Must be validated in us-east-1 by its owning root."
  type        = string
  default     = null
}
