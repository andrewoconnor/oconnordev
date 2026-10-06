variable "cost_export_bucket_name" {
  description = "GENERAL account bucket carrying the organization CUR 2.0 export."
  type = string
  default = ""
}
variable "cost_export_data_location" {
  description = "S3 data root for GENERAL account CUR delivery."
  type = string
  default = ""
}
