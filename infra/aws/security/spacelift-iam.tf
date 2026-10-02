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
  # checkov:skip=CKV_AWS_274:Accepted risk. This is the Spacelift deploy identity for the security account: the stack creates, updates and destroys the Config recorder, the delivery bucket and its policy, and the organization aggregator, and the role has no permissions boundary. Replacing AdministratorAccess with a scoped policy is a separate change that needs the stack's resource inventory and a boundary policy.
  role       = aws_iam_role.spacelift.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# ---------------------------------------------------------------------------
# Adoption of the bootstrap identity.
#
# This stack cannot create the role it assumes, so the `spacelift` role was
# created by hand in the security account to bootstrap it -- exactly as for the
# other three accounts. These blocks are what make the first apply adopt the
# existing role instead of failing with EntityAlreadyExists.
#
# The attachment is imported separately: adopting a role does not adopt its
# policy attachments.
#
# One-shot, and removed once the import has applied -- which is why no import
# block survives anywhere else in this repository. Until then, expect the first
# plan to show an import rather than a create.
#
# Expect the first plan to also show an in-place update to the role's trust
# policy if what was created by hand differs from the policy declared above.
# Review that delta before applying: it is the difference between the bootstrap
# identity and the identity the other three accounts use.
# ---------------------------------------------------------------------------

import {
  to = aws_iam_role.spacelift
  id = "spacelift"
}

import {
  to = aws_iam_role_policy_attachment.spacelift
  id = "spacelift/arn:aws:iam::aws:policy/AdministratorAccess"
}
