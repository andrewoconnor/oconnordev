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

import {
  to = aws_iam_role.spacelift
  id = "spacelift"
}

resource "aws_iam_role_policy_attachment" "spacelift" {
  role       = aws_iam_role.spacelift.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

import {
  to = aws_iam_role_policy_attachment.spacelift
  id = "spacelift/arn:aws:iam::aws:policy/AdministratorAccess"
}
