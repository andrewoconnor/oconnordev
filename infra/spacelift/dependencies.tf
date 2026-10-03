resource "spacelift_stack_dependency" "production_hermes_gateway" {
  stack_id            = spacelift_stack.accounts["production"].id
  depends_on_stack_id = spacelift_stack.accounts["hermes"].id
}

resource "spacelift_stack_dependency_reference" "production_hermes_gateway_origin" {
  stack_dependency_id = spacelift_stack_dependency.production_hermes_gateway.id
  output_name         = "hermes_gateway_origin_hostname"
  input_name          = "TF_VAR_hermes_gateway_origin_hostname"
}

resource "spacelift_stack_dependency" "security_general" {
  stack_id            = spacelift_stack.accounts["security"].id
  depends_on_stack_id = spacelift_stack.accounts["general"].id
}

resource "spacelift_stack_dependency" "hermes_security_gateway" {
  stack_id            = spacelift_stack.accounts["hermes"].id
  depends_on_stack_id = spacelift_stack.accounts["security"].id
}

resource "spacelift_stack_dependency_reference" "hermes_security_gateway_url" {
  stack_dependency_id = spacelift_stack_dependency.hermes_security_gateway.id
  output_name         = "security_gateway_url"
  input_name          = "TF_VAR_security_gateway_url"
}

resource "spacelift_stack_dependency_reference" "hermes_security_gateway_arn" {
  stack_dependency_id = spacelift_stack_dependency.hermes_security_gateway.id
  output_name         = "security_gateway_arn"
  input_name          = "TF_VAR_security_gateway_arn"
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
