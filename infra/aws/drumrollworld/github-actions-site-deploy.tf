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
  name               = "drumrollworld-site-deploy"
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

  # A server-side self-copy needs source read access. Restrict it to the
  # existing KTX2 prefix repaired by the site workflow; no other image reads.
  statement {
    sid       = "ReadGlobeKtxForMetadataRepair"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/images/globe/*.ktx2"]
  }

  statement {
    sid       = "InvalidateSiteDistribution"
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.drumrollworld.arn]
  }

  statement {
    sid       = "PreserveExternalImages"
    effect    = "Deny"
    actions   = ["s3:DeleteObject"]
    resources = ["${aws_s3_bucket.web.arn}/images/*"]
  }
}

resource "aws_iam_role_policy" "github_actions_site_deploy" {
  name   = "drumrollworld-site-deploy"
  role   = aws_iam_role.github_actions_site_deploy.id
  policy = data.aws_iam_policy_document.github_actions_site_deploy.json
}
