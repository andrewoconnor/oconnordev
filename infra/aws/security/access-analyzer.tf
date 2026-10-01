# An organization-level analyzer reads resource policies across every account
# in the organization, so it answers "does anything here grant cross-account or
# public access that I did not intend" without holding credentials in any other
# account. The external-access analyzer is provided at no additional charge.
#
# Deliberately not the unused-access analyzer: that one is billed per IAM role
# and user per month, which is the part of this account that would actually
# cost money. See the PR description.
resource "aws_accessanalyzer_analyzer" "organization" {
  analyzer_name = "oconnordev-organization"
  type          = "ORGANIZATION"
}
