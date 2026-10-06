variable "spacelift_run_id" {
  type = string
}

variable "cost_export_bucket_name" {
  description = "GENERAL stack output naming the organization CUR export bucket."
  type        = string
  default     = ""
}

variable "cost_export_data_location" {
  description = "GENERAL stack output identifying the CUR Parquet data root."
  type        = string
  default     = ""
}
