resource "aws_organizations_organization" "oconnordev" {
  feature_set = "ALL"

  aws_service_access_principals = [
    "iam.amazonaws.com",
    "sso.amazonaws.com",
    "config.amazonaws.com",
    "access-analyzer.amazonaws.com",
    "cloudtrail.amazonaws.com",
  ]

  enabled_policy_types = [
    "SERVICE_CONTROL_POLICY",
  ]
}

data "aws_ssoadmin_instances" "organization" {}

locals {
  identity_center_instance_arn = tolist(data.aws_ssoadmin_instances.organization.arns)[0]
  identity_store_id            = tolist(data.aws_ssoadmin_instances.organization.identity_store_ids)[0]

  identity_center_accounts = {
    "OCONNORDEV-GENERAL"    = data.aws_caller_identity.current.account_id
    "OCONNORDEV-PRODUCTION" = local.accounts["PRODUCTION"]
    "OCONNORDEV-HERMES"     = local.accounts["HERMES"]
    "OCONNORDEV-SECURITY"   = local.accounts["SECURITY"]
  }
}

resource "aws_identitystore_user" "andrew" {
  identity_store_id = local.identity_store_id
  user_name         = "andrew@oconnor.dev"
  display_name      = "Andrew O'Connor"

  name {
    given_name  = "Andrew"
    family_name = "O'Connor"
  }

  emails {
    value   = "andrew@oconnor.dev"
    primary = true
  }
}

resource "aws_identitystore_group" "administrators" {
  identity_store_id = local.identity_store_id
  display_name      = "Administrators"
  description       = "Human administrators for the oconnordev AWS Organization"
}

resource "aws_identitystore_group_membership" "andrew_administrator" {
  identity_store_id = local.identity_store_id
  group_id          = aws_identitystore_group.administrators.group_id
  member_id         = aws_identitystore_user.andrew.user_id
}

resource "aws_ssoadmin_permission_set" "administrators" {
  instance_arn     = local.identity_center_instance_arn
  name             = "Administrators"
  description      = "Administrator access for approved human administrators"
  session_duration = "PT1H"
}

resource "aws_ssoadmin_managed_policy_attachment" "administrator_access" {
  # checkov:skip=CKV_AWS_274:Accepted risk. This is the human administrator permission set: it is assigned only to the Administrators group (membership managed in aws_identitystore_group_membership.andrew_administrator) and only to the three organization accounts, with a one-hour session. Replacing AdministratorAccess with a narrower set is a separate change that needs a full inventory of what the human path must be able to do.
  instance_arn       = local.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.administrators.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

moved {
  from = aws_ssoadmin_account_assignment.administrators_security["482921124454"]
  to   = aws_ssoadmin_account_assignment.administrators["OCONNORDEV-SECURITY"]
}

resource "aws_ssoadmin_account_assignment" "administrators" {
  for_each = local.identity_center_accounts

  instance_arn       = local.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.administrators.arn
  principal_id       = aws_identitystore_group.administrators.group_id
  principal_type     = "GROUP"
  target_id          = each.value
  target_type        = "AWS_ACCOUNT"
}

resource "aws_iam_organizations_features" "centralized_root_access" {
  enabled_features = [
    "RootCredentialsManagement",
    "RootSessions",
  ]

  depends_on = [aws_organizations_organization.oconnordev]
}
