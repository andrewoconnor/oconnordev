# IAM Identity Center rollout (OCONNORDEV)

This configuration is intended to run from the `OCONNORDEV-GENERAL` management account in `us-east-1`.

## Bootstrap and apply sequence

1. Confirm the organization is in **All features** mode. The imported `aws_organizations_organization` resource declares `feature_set = "ALL"`; review the plan before applying.
2. Preserve the existing Organizations integrations and governance: IAM and IAM Identity Center service access (`iam.amazonaws.com`, `sso.amazonaws.com`) and the Service Control Policy policy type are explicitly retained in Terraform configuration. Review the import plan for any other changes before applying.
3. Enable an **organization instance** of IAM Identity Center in `us-east-1` from the management account's AWS console. AWS Organizations supports an organization instance in one Region, and its primary Region cannot be changed after creation. Do not create an account instance.
4. Keep the built-in Identity Center directory selected. Do not configure an external identity provider.
5. Configure MFA in the Identity Center settings to require MFA for users. Prefer a FIDO2 security key/passkey if available for this Identity Center instance; otherwise use an authenticator app. The Terraform AWS provider does not provision a user's MFA device or enforce the instance's MFA policy, so complete this setup in the console before granting access.
6. Verify the Identity Center instance is discoverable in `us-east-1`, then review and apply the Terraform plan. It imports the existing Organization and creates the directory user/group, membership, permission set and assignments.
7. Complete the user's email verification/credential setup. Retrieve the actual AWS access portal URL from Identity Center settings, sign in as `andrew@oconnor.dev`, complete MFA enrollment, and verify the three account tiles.
8. From the management account, verify centralized root access management is available. The `aws_iam_organizations_features` resource enables `RootCredentialsManagement` and `RootSessions`; these are separate from ordinary `AdministratorAccess` console sessions.

## Resources managed

- Existing Organization `o-4eua3nehe1` (import ID; management account `905418422177`), with all features declared and existing IAM/Identity Center service access plus SCP policy type preserved.
- Built-in-directory user `Andrew O'Connor` (`andrew@oconnor.dev`) and `Administrators` group.
- `Administrators` permission set with the AWS-managed `AdministratorAccess` policy and a one-hour session duration.
- Group assignments in accounts `905418422177` (GENERAL), `767397796791` (PRODUCTION), and `421680664125` (HERMES).
- Organization-wide centralized root credentials management and root sessions.

This configuration does not modify `iamadmin`, any IAM access keys, Spacelift, GitHub Actions, or workload authentication. Do not remove or rotate the existing `iamadmin` access key until its separate Spacelift migration is explicitly approved.
