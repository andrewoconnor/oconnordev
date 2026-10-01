data "aws_iam_policy_document" "spacelift" {
  statement {
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::905418422177:role/spacelift"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "spacelift" {
  name               = "spacelift"
  assume_role_policy = data.aws_iam_policy_document.spacelift.json
}

resource "aws_iam_role_policy_attachment" "spacelift" {
  role       = aws_iam_role.spacelift.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
