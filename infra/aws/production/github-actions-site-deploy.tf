variable "retain_legacy_github_oidc_provider" {
  description = "Temporarily retain the old PRODUCTION OIDC provider and direct GitHub trust during broker cutover. The true setting adds the old master-only OIDC trust alongside the TOOLS broker trust; remove the runtime override only after the chained workflow succeeds."
  type        = bool
  default     = false
}

data "aws_iam_policy_document" "github_actions_site_deploy_trust" {
  statement {
    sid     = "ToolsBrokerOnly"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [local.tools_github_actions_broker_role_arn]
    }
  }

  dynamic "statement" {
    for_each = var.retain_legacy_github_oidc_provider ? [true] : []
    content {
      sid     = "GitHubActionsMasterOnly"
      effect  = "Allow"
      actions = ["sts:AssumeRoleWithWebIdentity"]

      principals {
        type        = "Federated"
        identifiers = [aws_iam_openid_connect_provider.github_actions[0].arn]
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
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  count          = var.retain_legacy_github_oidc_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_actions_site_deploy" {
  name               = "oconnordev-site-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_actions_site_deploy_trust.json
}

data "aws_iam_policy_document" "github_actions_site_deploy" {
  statement {
    sid       = "ListSiteBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.web.arn]
  }

  statement {
    sid    = "SyncSiteObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.web.arn}/*"]
  }

  statement {
    sid       = "InvalidateSiteDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.oconnordev.arn]
  }
}

resource "aws_iam_role_policy" "github_actions_site_deploy" {
  name   = "oconnordev-site-deploy"
  role   = aws_iam_role.github_actions_site_deploy.id
  policy = data.aws_iam_policy_document.github_actions_site_deploy.json
}
