variable "cost_export_projection_start_month" {
  description = "First CUR billing month exposed by Athena partition projection (YYYY-MM)."
  type        = string
  default     = "2024-01"
  validation {
    condition     = can(regex("^[0-9]{4}-(0[1-9]|1[0-2])$", var.cost_export_projection_start_month))
    error_message = "Use a valid month in YYYY-MM format."
  }
}
variable "athena_bytes_scanned_cutoff_per_query" {
  description = "Athena per-query bytes scanned cutoff; not a monthly spending cap."
  type = number
  default = 1073741824
  validation {
    condition = var.athena_bytes_scanned_cutoff_per_query > 0
    error_message = "The cutoff must be positive."
  }
}
