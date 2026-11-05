resource "aws_organizations_policy" "deny_leave_and_close_account" {
  name        = "DenyLeaveAndCloseAccount"
  description = "Prevents member accounts from leaving the organization and self closure"
  type        = "SERVICE_CONTROL_POLICY"
  content     = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Deny\",\"Action\":[\"organizations:LeaveOrganization\",\"account:CloseAccount\"],\"Resource\":\"*\"}]}"
}

resource "aws_organizations_policy_attachment" "deny_leave_and_close_account_root" {
  policy_id = aws_organizations_policy.deny_leave_and_close_account.id
  target_id = aws_organizations_organization.oconnordev.roots[0].id
}
