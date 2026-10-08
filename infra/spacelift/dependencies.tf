resource "spacelift_stack_dependency" "production_tools_gateway" {
  stack_id            = spacelift_stack.accounts["production"].id
  depends_on_stack_id = spacelift_stack.accounts["tools"].id
}

resource "spacelift_stack_dependency_reference" "production_tools_gateway_origin" {
  stack_dependency_id = spacelift_stack_dependency.production_tools_gateway.id
  output_name         = "tools_gateway_origin_hostname"
  input_name          = "TF_VAR_hermes_gateway_origin_hostname"
}

resource "spacelift_stack_dependency" "security_general" {
  stack_id            = spacelift_stack.accounts["security"].id
  depends_on_stack_id = spacelift_stack.accounts["general"].id
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

resource "spacelift_stack_dependency" "tools_security_gateway" {
  stack_id            = spacelift_stack.accounts["tools"].id
  depends_on_stack_id = spacelift_stack.accounts["security"].id
}

resource "spacelift_stack_dependency_reference" "tools_security_gateway_url" {
  stack_dependency_id = spacelift_stack_dependency.tools_security_gateway.id
  output_name         = "security_gateway_url"
  input_name          = "TF_VAR_security_gateway_url"
}

resource "spacelift_stack_dependency_reference" "tools_security_gateway_arn" {
  stack_dependency_id = spacelift_stack_dependency.tools_security_gateway.id
  output_name         = "security_gateway_arn"
  input_name          = "TF_VAR_security_gateway_arn"
}

resource "spacelift_stack_dependency_reference" "tools_security_logs_sink" {
  stack_dependency_id = spacelift_stack_dependency.tools_security_gateway.id
  output_name         = "cloudwatch_logs_sink_arn"
  input_name          = "TF_VAR_security_logs_sink_arn"
}

resource "spacelift_stack_dependency" "production_security_logs" {
  stack_id            = spacelift_stack.accounts["production"].id
  depends_on_stack_id = spacelift_stack.accounts["security"].id
}

resource "spacelift_stack_dependency_reference" "production_security_logs_sink" {
  stack_dependency_id = spacelift_stack_dependency.production_security_logs.id
  output_name         = "cloudwatch_logs_sink_arn"
  input_name          = "TF_VAR_security_logs_sink_arn"
}

resource "spacelift_stack_dependency" "github_repository_config_production" {
  count = var.enable_github_repository_config ? 1 : 0

  stack_id            = spacelift_stack.github_repository_config[0].id
  depends_on_stack_id = spacelift_stack.accounts["production"].id
}

resource "spacelift_stack_dependency_reference" "github_repository_config_deploy_role_arn" {
  count = var.enable_github_repository_config ? 1 : 0

  stack_dependency_id = spacelift_stack_dependency.github_repository_config_production[0].id
  output_name         = "oconnordev_site_deploy_role_arn"
  input_name          = "TF_VAR_oconnordev_site_deploy_role_arn"
}

resource "spacelift_stack_dependency_reference" "github_repository_config_cloudfront_id" {
  count = var.enable_github_repository_config ? 1 : 0

  stack_dependency_id = spacelift_stack_dependency.github_repository_config_production[0].id
  output_name         = "oconnordev_cloudfront_distribution_id"
  input_name          = "TF_VAR_oconnordev_cloudfront_distribution_id"
}

resource "spacelift_stack_dependency" "github_repository_config_tools" {
  count = var.enable_github_repository_config ? 1 : 0

  stack_id            = spacelift_stack.github_repository_config[0].id
  depends_on_stack_id = spacelift_stack.accounts["tools"].id
}

resource "spacelift_stack_dependency_reference" "github_repository_config_tools_broker_role_arn" {
  count = var.enable_github_repository_config ? 1 : 0

  stack_dependency_id = spacelift_stack_dependency.github_repository_config_tools[0].id
  output_name         = "tools_github_actions_broker_role_arn"
  input_name          = "TF_VAR_oconnordev_tools_github_actions_broker_role_arn"
}
