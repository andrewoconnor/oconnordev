# ---------------------------------------------------------------------------
# The security account: delegated-administrator registration.
#
# These are management-account operations, so they live here rather than in
# infra/aws/security. The account itself is created out of band in the
# Organizations console and is discovered by name below, so this stack needs no
# manual account ID input.
#
# The registrations are what let the security account run the organization-wide
# Config aggregator and the organization-level Access Analyzer. Nothing here
# grants the security account permission to read another account directly --
# both services read through their own service-linked mechanism.
# ---------------------------------------------------------------------------

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

# Both services require trusted access to be enabled for the organization
# before an account can be registered as their delegated administrator. The
# trusted access list itself is declared on aws_organizations_organization in
# identity-center.tf.
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

# CloudTrail delegated administration. The security account gains the same
# administrative tasks over the organization's trails that the management
# account has, without becoming the owner of them:
#
#   https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-delegated-administrator.html
#   "The organization's management account remains the owner of any CloudTrail
#    organization resources the delegated administrator creates."
#   "Adding a delegated administrator does not alter the management or operation
#    of the organization's trails."
#
# So this is additive: the management account still owns the trail, which is
# created and managed from the security account's own stack
# (infra/aws/security/cloudtrail.tf). Nothing here needs to change if that
# account is ever replaced.
#
# The service-linked role below is required here, and it is easy to miss.
# Registering a delegated administrator through the Organizations API does NOT
# create CloudTrail's service-linked roles, and a call made from the security
# account does not create them in the management account either:
#
#   "When you add a delegated administrator using the AWS Organizations CLI or
#    API operation, CloudTrail service-linked roles won't be created
#    automatically if they don't exist. The service-linked roles are only created
#    when you make a call from the management account directly to the CloudTrail
#    service."
#
# Creating the organization trail from the security account is not such a call,
# so the management account's role is created here instead. This mirrors the
# Access Analyzer role further down, which exists for the same reason and for the
# same shape of failure.
#
# If the role already exists in this account, apply fails with
#   InvalidInput: Service role name AWSServiceRoleForCloudTrail has been taken
# in this account
# and the fix is to adopt the existing role rather than recreate it:
#   terraform import aws_iam_service_linked_role.cloudtrail \
#     arn:aws:iam::905418422177:role/aws-service-role/cloudtrail.amazonaws.com/AWSServiceRoleForCloudTrail
resource "aws_organizations_delegated_administrator" "cloudtrail" {
  account_id        = local.security_account_ids[0]
  service_principal = "cloudtrail.amazonaws.com"

  depends_on = [terraform_data.security_account_guard]
}

resource "aws_iam_service_linked_role" "cloudtrail" {
  aws_service_name = "cloudtrail.amazonaws.com"
}

# An organization-level analyzer can only be created by the delegated
# administrator once the Access Analyzer service-linked role exists in the
# management account. Creating a management-account analyzer would create it
# too, but that is a second analyzer nobody reads; creating the role directly
# is the documented way to enable the service without one:
#
#   https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-using-service-linked-roles.html
#   "In the AWS CLI or the AWS API, create a service-linked role with the
#    access-analyzer.amazonaws.com service name."
#
# Without this, the security stack's apply fails with:
#   ConflictException: Access Analyzer Service Linked Role is not in the
#   organizational management account
#
# The security stack depends on this one, so the ordering is already handled.
resource "aws_iam_service_linked_role" "access_analyzer" {
  aws_service_name = "access-analyzer.amazonaws.com"
}

# Human access to the new account, through the same Administrators permission
# set the other three accounts use. Empty until the account exists, so this is
# a no-op on the first plan.
resource "aws_ssoadmin_account_assignment" "administrators_security" {
  for_each = toset(local.security_account_ids)

  instance_arn       = local.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.administrators.arn
  principal_id       = aws_identitystore_group.administrators.group_id
  principal_type     = "GROUP"
  target_id          = each.value
  target_type        = "AWS_ACCOUNT"
}
