variable "spacelift_run_id" {
  type = string
}
variable "oconnordev_cloudfront_distribution_id" {
  description = "Compatibility output only; set to the verified existing distribution before the owner-operated state handoff. Resume now owns the distribution."
  type        = string
  default     = "E2YPD9UPXXK53Y"
}
