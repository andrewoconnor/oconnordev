resource "spacelift_aws_integration" "oconnordev" {
  name = "oconnordev"

  role_arn                       = "arn:aws:iam::${jsondecode(file("${path.module}/../aws/accounts.json"))["GENERAL"]}:role/spacelift"
  generate_credentials_in_worker = false
  space_id                       = spacelift_space.oconnordev.id
}

resource "spacelift_environment_variable" "general_spacelift_integration_id" {
  stack_id    = spacelift_stack.accounts["general"].id
  name        = "TF_VAR_spacelift_integration_id"
  value       = spacelift_aws_integration.oconnordev.id
  write_only  = false
  description = "Spacelift AWS integration ID used by the management-account IAM role trust policy"
}

resource "spacelift_environment_variable" "general_spacelift_account_id" {
  stack_id    = spacelift_stack.accounts["general"].id
  name        = "TF_VAR_spacelift_account_id"
  value       = data.spacelift_account.current.aws_account_id
  write_only  = false
  description = "Spacelift AWS account ID used by the management-account IAM role trust policy"
}

resource "spacelift_aws_integration_attachment" "accounts" {
  for_each = local.account_stacks

  integration_id = spacelift_aws_integration.oconnordev.id
  stack_id       = spacelift_stack.accounts[each.key].id
  read           = true
  write          = true
}
