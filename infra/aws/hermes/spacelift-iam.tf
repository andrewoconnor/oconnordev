data "aws_iam_policy_document" "spacelift" {
  statement {
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.accounts["GENERAL"]}:role/spacelift"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "spacelift" {
  name               = "spacelift"
  assume_role_policy = data.aws_iam_policy_document.spacelift.json
}

resource "aws_iam_role_policy_attachment" "spacelift" {
  # checkov:skip=CKV_AWS_274:Accepted risk. This is the Spacelift deploy identity for the Hermes account: the stack creates, updates and destroys AgentCore, Cognito, Lambda and IAM resources whose full resource set is not enumerable in advance, and the role has no permissions boundary. Replacing AdministratorAccess with a scoped policy is a separate change that needs the stack's resource inventory and a boundary policy.
  role       = aws_iam_role.spacelift.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
