locals {
  github_actions_broker_role_name = "oconnordev-github-actions-broker"
  production_site_deploy_role_arn = "arn:aws:iam::${local.accounts["PRODUCTION"]}:role/oconnordev-site-deploy"
}

data "aws_iam_policy_document" "github_actions_broker_trust" {
  statement {
    sid     = "GitHubActionsMasterOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:andrewoconnor/oconnordev:ref:refs/heads/master"]
    }
  }
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_actions_broker" {
  name               = local.github_actions_broker_role_name
  assume_role_policy = data.aws_iam_policy_document.github_actions_broker_trust.json
}

data "aws_iam_policy_document" "github_actions_broker_assume_production" {
  statement {
    sid       = "AssumeOnlyProductionSiteDeployRole"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = [local.production_site_deploy_role_arn]
  }
}

resource "aws_iam_role_policy" "github_actions_broker_assume_production" {
  name   = "oconnordev-github-actions-broker-assume-production"
  role   = aws_iam_role.github_actions_broker.id
  policy = data.aws_iam_policy_document.github_actions_broker_assume_production.json
}
