# Shared tools images; tag prefixes are a naming convention, not IAM isolation.
# No lifecycle cleanup: retained digests may be active/rollback images for any target.
resource "aws_ecr_repository" "tools_images" {
  # checkov:skip=CKV_AWS_136:AWS-managed ECR encryption avoids a new paid customer-managed KMS key for this low-duty personal workload.
  name                 = "oconnordev-tools"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  encryption_configuration { encryption_type = "AES256" }
  image_scanning_configuration { scan_on_push = true }
}

# Shared repository does not imply shared invocation/pull authorization.
# Explicitly review each future function SourceArn before extending this policy.
resource "aws_ecr_repository_policy" "tools_images" {
  repository = aws_ecr_repository.tools_images.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "ToolsLambdaPull"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
      Condition = { ArnLike = { "aws:SourceArn" = [local.thundermail_function_arn] } }
    }]
  })
}

# Image publisher: no Lambda update, role pass, secret access or apply.
# Repository-scoped, not tag-scoped: this role can push any tag in the shared repo.
resource "aws_iam_role" "tools_image_publisher" {
  name = "hermes-tools-image-publisher"
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

resource "aws_iam_role_policy" "tools_image_publisher" {
  name = "ecr-push-and-readback"
  role = aws_iam_role.tools_image_publisher.id
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
        Resource = aws_ecr_repository.tools_images.arn
      }
    ]
  })
}
