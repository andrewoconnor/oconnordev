# Import and manage the existing AWS Organization from the management account.
resource "aws_organizations_organization" "oconnordev" {
  feature_set = "ALL"

  # Preserve existing organization integrations and governance while importing.
  aws_service_access_principals = [
    "iam.amazonaws.com",
    "sso.amazonaws.com",
  ]

  enabled_policy_types = [
    "SERVICE_CONTROL_POLICY",
  ]
}

import {
  to = aws_organizations_organization.oconnordev
  id = "o-4eua3nehe1"
}

# IAM Identity Center must first be enabled as an organization instance in
# us-east-1 from the AWS console. This data source then reads that instance.
data "aws_ssoadmin_instances" "organization" {}

locals {
  identity_center_instance_arn = tolist(data.aws_ssoadmin_instances.organization.arns)[0]
  identity_store_id             = tolist(data.aws_ssoadmin_instances.organization.identity_store_ids)[0]

  identity_center_accounts = {
    "OCONNORDEV-GENERAL"    = "905418422177"
    "OCONNORDEV-PRODUCTION" = "767397796791"
    "OCONNORDEV-HERMES"     = "421680664125"
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
  instance_arn       = local.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.administrators.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
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

# Enables centrally managed root credentials and task-scoped root sessions for
# member accounts. This does not delete or modify the iamadmin IAM user/key.
resource "aws_iam_organizations_features" "centralized_root_access" {
  enabled_features = [
    "RootCredentialsManagement",
    "RootSessions",
  ]

  depends_on = [aws_organizations_organization.oconnordev]
}
