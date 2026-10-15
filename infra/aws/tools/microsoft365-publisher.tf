# Independent image publisher: no Lambda update, role pass, secret access or apply.
resource "aws_iam_role" "microsoft365_image_publisher" {
  name = "hermes-microsoft365-image-publisher"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "repo:andrewoconnor/oconnordev:ref:refs/heads/master"
      } }
    }]
  })
}

resource "aws_iam_role_policy" "microsoft365_image_publisher" {
  name = "only-microsoft365-ecr-push-and-readback"
  role = aws_iam_role.microsoft365_image_publisher.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:DescribeImages", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = aws_ecr_repository.microsoft365.arn
      }
    ]
  })
}
