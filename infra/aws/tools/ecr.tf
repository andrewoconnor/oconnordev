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
      Condition = { ArnLike = { "aws:SourceArn" = [local.microsoft365_function_arn, local.thundermail_function_arn] } }
    }]
  })
}

moved {
  from = aws_ecr_repository_policy.microsoft365_lambda_pull
  to   = aws_ecr_repository_policy.tools_images
}
