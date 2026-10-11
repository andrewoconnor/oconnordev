variable "spacelift_run_id" { type = string }
variable "site_zone_id" {
  description = "Existing oconnor.dev hosted zone, still owned by production and shared with the Hermes endpoint."
  type        = string
}
variable "dnssec_key_arn" {
  description = "Production-owned us-east-1 DNSSEC signing key ARN (not an alias lookup)."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:kms:us-east-1:[0-9]{12}:key/[a-f0-9-]+$", var.dnssec_key_arn))
    error_message = "Pass the production DNSSEC key ARN in us-east-1, not a key alias or lookup name."
  }
}
variable "site_certificate_arn" {
  description = "Production-owned wildcard certificate shared with mcp.oconnor.dev."
  type        = string
}
