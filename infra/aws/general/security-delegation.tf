resource "aws_organizations_delegated_administrator" "config" {
  account_id        = local.accounts["SECURITY"]
  service_principal = "config.amazonaws.com"

  depends_on = [aws_organizations_organization.oconnordev]
}

resource "aws_organizations_delegated_administrator" "access_analyzer" {
  account_id        = local.accounts["SECURITY"]
  service_principal = "access-analyzer.amazonaws.com"

  depends_on = [aws_organizations_organization.oconnordev]
}

resource "aws_organizations_delegated_administrator" "cloudtrail" {
  account_id        = local.accounts["SECURITY"]
  service_principal = "cloudtrail.amazonaws.com"

  depends_on = [aws_organizations_organization.oconnordev]
}

resource "aws_iam_service_linked_role" "cloudtrail" {
  aws_service_name = "cloudtrail.amazonaws.com"
}

resource "aws_iam_service_linked_role" "access_analyzer" {
  aws_service_name = "access-analyzer.amazonaws.com"
}