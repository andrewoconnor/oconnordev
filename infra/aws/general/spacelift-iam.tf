variable "spacelift_account_id" {
  description = "AWS account ID of the Spacelift service account, passed from the Spacelift management stack."
  type        = string
}

variable "spacelift_integration_id" {
  description = "ID of the Spacelift AWS integration, passed from the Spacelift management stack."
  type        = string
}

locals {
  spacelift_iam_role_name = "spacelift"
}

data "aws_iam_policy_document" "spacelift_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${var.spacelift_account_id}:root"]
    }

    actions = ["sts:AssumeRole"]

    condition {
      test     = "StringLike"
      variable = "sts:ExternalId"
      values   = ["andrewoconnor@${var.spacelift_integration_id}@*"]
    }
  }
}

resource "aws_iam_role" "spacelift" {
  name               = local.spacelift_iam_role_name
  assume_role_policy = data.aws_iam_policy_document.spacelift_assume_role.json
}

resource "aws_iam_role_policy_attachment" "spacelift" {
  # checkov:skip=CKV_AWS_274:Accepted risk. This is the Spacelift deploy identity for the general account: the stack creates, updates and destroys organization, Identity Center and IAM resources whose full resource set is not enumerable in advance, and the role has no permissions boundary. Replacing AdministratorAccess with a scoped policy is a separate change that needs the stack's resource inventory and a boundary policy.
  role       = aws_iam_role.spacelift.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
