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

# The policy already exists in the live organization and is attached to its root.
# Import both objects into General state instead of creating a duplicate policy.
import {
  to = aws_organizations_policy.deny_leave_and_close_account
  id = "p-3x6rql11"
}

import {
  to = aws_organizations_policy_attachment.deny_leave_and_close_account_root
  id = "r-qmpg:p-3x6rql11"
}
