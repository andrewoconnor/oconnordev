
data "aws_organizations_organization" "current" {}

locals {
  security_account_name = "OCONNORDEV-SECURITY"

  security_account_ids = [
    for account in data.aws_organizations_organization.current.accounts :
    account.id if account.name == local.security_account_name
  ]
}

resource "terraform_data" "security_account_guard" {
  input = local.security_account_ids

  lifecycle {
    precondition {
      condition     = length(local.security_account_ids) == 1
      error_message = "Expected exactly one organization account named ${local.security_account_name}, found ${length(local.security_account_ids)}. Create the account in the Organizations console and move it into the Security OU before re-running this stack."
    }
  }
}

resource "aws_organizations_delegated_administrator" "config" {
  account_id        = local.security_account_ids[0]
  service_principal = "config.amazonaws.com"

  depends_on = [terraform_data.security_account_guard]
}

resource "aws_organizations_delegated_administrator" "access_analyzer" {
  account_id        = local.security_account_ids[0]
  service_principal = "access-analyzer.amazonaws.com"

  depends_on = [terraform_data.security_account_guard]
}

resource "aws_organizations_delegated_administrator" "cloudtrail" {
  account_id        = local.security_account_ids[0]
  service_principal = "cloudtrail.amazonaws.com"

  depends_on = [terraform_data.security_account_guard]
}

resource "aws_iam_service_linked_role" "cloudtrail" {
  aws_service_name = "cloudtrail.amazonaws.com"
}

resource "aws_iam_service_linked_role" "access_analyzer" {
  aws_service_name = "access-analyzer.amazonaws.com"
}

resource "aws_ssoadmin_account_assignment" "administrators_security" {
  for_each = toset(local.security_account_ids)

  instance_arn       = local.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.administrators.arn
  principal_id       = aws_identitystore_group.administrators.group_id
  principal_type     = "GROUP"
  target_id          = each.value
  target_type        = "AWS_ACCOUNT"
}
