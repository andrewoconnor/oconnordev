resource "spacelift_stack_dependency" "security_general" {
  stack_id            = spacelift_stack.aws_security.id
  depends_on_stack_id = spacelift_stack.aws_general.id
}

resource "spacelift_stack_dependency_reference" "security_cost_export_bucket_name" {
  stack_dependency_id = spacelift_stack_dependency.security_general.id
  output_name         = "cost_export_bucket_name"
  input_name          = "TF_VAR_cost_export_bucket_name"
}
resource "spacelift_stack_dependency_reference" "security_cost_export_data_location" {
  stack_dependency_id = spacelift_stack_dependency.security_general.id
  output_name         = "cost_export_data_location"
  input_name          = "TF_VAR_cost_export_data_location"
}
