variable "spacelift_run_id" {
  type = string
}
variable "dnssec_key_arn" {
  description = "DNSSEC signing key exported by the production stack."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:kms:us-east-1:[0-9]{12}:key/[a-f0-9-]+$", var.dnssec_key_arn))
    error_message = "Pass the production DNSSEC key ARN in us-east-1, not a key alias or lookup name."
  }
}
