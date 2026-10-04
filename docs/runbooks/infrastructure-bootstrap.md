# Infrastructure bootstrap and state safety

Use this runbook for new stack bootstraps and state-sensitive AWS changes. The current account boundaries and dependency graph are described in [the architecture overview](../architecture/README.md).

## Account stack order

1. Apply `infra/spacelift` first to create or update the managed stack graph and AWS integration. The account bootstrap roles must already exist because each account stack assumes its own role.
2. Apply `infra/aws/general` before `infra/aws/security`. For a fresh General stack with none of the gated audit resources in state, follow the audit enablement procedure below.
3. Apply `infra/aws/security` and verify the CloudTrail and Config destination buckets and policies before enabling the General audit writers.
4. Apply `infra/aws/tools` after Security; its AWS target consumes the Security gateway URL and ARN through Spacelift references. Apply `infra/aws/production` after TOOLS because the production CloudFront endpoint consumes the TOOLS output. Keep PRODUCTION's `TF_VAR_hermes_gateway_origin_hostname` wired from TOOLS's `tools_gateway_origin_hostname`; if that dependency is missing, gated CloudFront resources can plan for deletion.
5. For refactor changes, inspect every speculative plan. Require only intended address moves, in-place changes, or no-ops; a merge does not itself apply infrastructure.

## Organization audit enablement and state safety

`enable_management_account_audit` defaults to `true`, which enables the management-account CloudTrail and Config resources. On a genuinely fresh General stack—with none of the gated resources present in state—set `TF_VAR_enable_management_account_audit=false` for its first apply so Organizations trusted access and delegated-administrator registration can be established before destination buckets exist. Confirm that the plan has no destroys for gated addresses. The delegated-administrator registrations must follow the Organizations resource so trusted access is enabled first.

After Security has created and verified both destination buckets and their delivery policies, set the flag to `true` on a fresh stack and re-plan General. Before applying, inspect the full plan and import any existing CloudTrail or Config resource that is absent from General state. Require no destroy/recreate of an existing audit resource. If a required destination bucket is absent, finish the Security apply first and re-plan General.

Do not set the flag to `false` on an established state as a temporary workaround: the variable gates resources with `count`, so changing it from one to zero plans their deletion. For the current General state, the organization trail is `aws_cloudtrail.organization[0]`; the Config recorder role, attachment, recorder, delivery channel, and recorder status are likewise managed at their `[0]` addresses. Re-read live state and the plan before changing this setting, and reconcile/import existing resources rather than replacing them.

## TOOLS account and GitHub Actions deployment

The live account is `OCONNORDEV-TOOLS` (`421680664125`); `infra/aws/accounts.json` is the repository source for its ID. Terraform does not rename the AWS account or change its primary email. The existing Spacelift stack ID `oconnordev-hermes` is retained for state continuity, with display name `oconnordev-tools` and project root `infra/aws/tools`, managed by `infra/spacelift`; do not create a replacement stack or restore a separate root override.

The deployment role chain is GitHub OIDC → `oconnordev-github-actions-broker` in TOOLS → the existing `oconnordev-site-deploy` role in PRODUCTION. The broker's trust is limited to the `andrewoconnor/oconnordev` `master` subject and `sts.amazonaws.com` audience, and its only permission is to assume that exact PRODUCTION role. Before applying TOOLS in a new environment, inspect account `421680664125` for the `https://token.actions.githubusercontent.com` provider and the broker role. If either already exists outside TOOLS state, import/reconcile it at `aws_iam_openid_connect_provider.github_actions` or `aws_iam_role.github_actions_broker` rather than attempting a duplicate create.

The GitHub repository-configuration stack gets `OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` from the TOOLS output. Before its first apply in a new environment, check whether that Actions variable already exists outside Terraform state; if so, import it as `github_actions_variable.tools_github_actions_broker_role_arn` with provider ID `oconnordev:OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` before applying. After a deployment-workflow change, run the site workflow on `master` and verify both role assumptions, S3 sync, and CloudFront invalidation; changing a workflow file alone does not trigger a deployment.
