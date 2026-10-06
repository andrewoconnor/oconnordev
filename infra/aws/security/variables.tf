variable "cost_export_bucket_name" {
  description = "GENERAL account bucket containing the organization CUR export."
  type        = string
  default     = ""
}
variable "cost_export_data_location" {
  description = "S3 data root for GENERAL CUR deliveries."
  type        = string
  default     = ""
}
