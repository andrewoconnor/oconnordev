# Moving the Spacelift AWS IAM role into the management-account stack

`aws_iam_role.spacelift` and its `AdministratorAccess` attachment belong to the AWS management account and are managed by the AWS provider, so they live in `infra/stacks/general`. The Spacelift integration and its stack attachments remain in `infra/stacks/spacelift` because they are Spacelift-provider resources.

This is a two-state handoff; it must not destroy/recreate the IAM role:

1. Apply `infra/stacks/spacelift` first. The management stack provisions two non-secret `TF_VAR_` environment values on the General stack, keeps the AWS integration pointed at the same IAM role ARN, and uses `removed` blocks with `destroy = false` to detach the IAM resources from its state without deleting them.
2. Then run the General stack plan. Its import blocks import the existing IAM role and policy attachment into the General stack state. Confirm the role trust policy is unchanged and the plan does not replace or alter the live IAM role or policy attachment.
3. Apply the General stack only after its plan is clean apart from the expected imports. Verify the General stack's AWS integration attachments and a tracked stack run before considering the move complete.

The Spacelift integration ID and Spacelift service account ID are passed as ordinary, non-secret stack environment variables, not credentials. The integration itself and its three stack attachments stay managed in the Spacelift stack. This change does not rotate or remove the `iamadmin` key and does not migrate Spacelift authentication.
