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
