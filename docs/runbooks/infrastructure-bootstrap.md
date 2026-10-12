# Infrastructure bootstrap and state safety

Use this runbook for new stack bootstraps and state-sensitive AWS changes. The current account boundaries and dependency graph are described in [the architecture overview](../architecture/README.md).

## Stack apply order

1. Apply `infra/spacelift` first to create or update the managed stack graph and AWS integration. The four organization account stacks assume their account's `role/spacelift`; the DrumrollWorld static-site workload stack also uses the PRODUCTION account's role.
2. Apply `infra/aws/general` before `infra/aws/security`. For a fresh General stack with none of the gated audit resources in state, follow the audit enablement procedure below.
3. Apply `infra/aws/security` and verify the CloudTrail and Config destination buckets and policies before enabling the General audit writers.
4. Apply `infra/aws/tools` after Security; its AWS target consumes the Security gateway URL and ARN through Spacelift references. Apply `infra/aws/production` after TOOLS because the production CloudFront endpoint consumes the TOOLS output. Keep PRODUCTION's `TF_VAR_hermes_gateway_origin_hostname` wired from TOOLS's `tools_gateway_origin_hostname`; if that dependency is missing, gated CloudFront resources can plan for deletion.
5. For refactor changes, inspect every speculative plan. Require only intended address moves, in-place changes, or no-ops; a merge does not itself apply infrastructure.

## Organization audit enablement and state safety

`enable_management_account_audit` defaults to `true`, which enables the management-account CloudTrail and Config resources. On a genuinely fresh General stack—with none of the gated resources present in state—set `TF_VAR_enable_management_account_audit=false` for its first apply so Organizations trusted access and delegated-administrator registration can be established before destination buckets exist. Confirm that the plan has no destroys for gated addresses. The delegated-administrator registrations must follow the Organizations resource so trusted access is enabled first.

After Security has created and verified both destination buckets and their delivery policies, set the flag to `true` on a fresh stack and re-plan General. Before applying, inspect the full plan and import any existing CloudTrail or Config resource that is absent from General state. Require no destroy/recreate of an existing audit resource. If a required destination bucket is absent, finish the Security apply first and re-plan General.

Do not set the flag to `false` on an established state as a temporary workaround: the variable gates resources with `count`, so changing it from one to zero plans their deletion. For the current General state, the organization trail is `aws_cloudtrail.organization[0]`; the Config recorder role, attachment, recorder, delivery channel, and recorder status are likewise managed at their `[0]` addresses. Re-read live state and the plan before changing this setting, and reconcile/import existing resources rather than replacing them.

## TOOLS account and GitHub Actions deployment

The live account is `OCONNORDEV-TOOLS` (`421680664125`); `infra/aws/accounts.json` is the repository source for its ID. Its Spacelift stack is managed by `infra/spacelift` and uses the OpenTofu root `infra/aws/tools`; preserve the existing stack and state rather than creating a replacement.

The deployment role chain is GitHub OIDC → `oconnordev-github-actions-broker` in TOOLS → the existing `oconnordev-site-deploy` role in PRODUCTION. The broker's trust is limited to `repo:andrewoconnor/oconnordev:environment:oconnordev-production` and `sts.amazonaws.com` audience, and its only permission is to assume that exact PRODUCTION role. Before applying TOOLS in a new environment, inspect account `421680664125` for the `https://token.actions.githubusercontent.com` provider and the broker role. If either already exists outside TOOLS state, import/reconcile it at `aws_iam_openid_connect_provider.github_actions` or `aws_iam_role.github_actions_broker` rather than attempting a duplicate create.

The GitHub repository-configuration stack gets `OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` from the TOOLS output. Before its first apply in a new environment, check whether that Actions variable already exists outside OpenTofu state; if so, import it as `github_actions_variable.tools_github_actions_broker_role_arn` with provider ID `oconnordev:OCONNORDEV_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` before applying. After a deployment-workflow change, run the site workflow on `master` and verify both role assumptions, S3 sync, and CloudFront invalidation; both workflows now include their own workflow path in master-push triggers.


## Tested-artifact environment cutover

The user must review/apply infrastructure from the reviewed change **before
merging the auto-deploy workflow cutover**, or explicitly pause both workflows
until the cutover is complete. These agents do not apply or deploy. Staging the
new trust temporarily stops old ref-subject workflows; schedule that pause.

1. **Stage both GitHub environments before any IAM environment trust.** Use a
   separate, user-owned GitHub UI bootstrap in `andrewoconnor/oconnordev`:
   Settings → Environments. Create/inspect `oconnordev-production` and
   `drumrollworld-production`; select custom deployment branch policies
   ("Selected branches and tags"), allow exactly branch `master`, and require
   no tag policy or other branch pattern. Do not rely on workflow jobs to
   auto-create environments: an unprotected environment can issue an environment
   subject from a non-master ref. Keep IAM on its existing trust during this
   bootstrap, including the interval between environment creation and protection.
   Do not run the dependent repository stack yet: it consumes TOOLS and DrumrollWorld
   outputs, including the new broker ARN. This separate bootstrap needs neither
   producer apply nor that ARN, so it avoids the dependency cycle. Record both
   environment names and master deployment-policy IDs for later state imports;
   do not create a replacement stack/state.
2. **Read back and test both environment gates before IAM changes.** Read both
   environments and all their deployment branch policies from GitHub; require
   `protected_branches=false`, `custom_branch_policies=true`, and exactly one
   branch policy named `master`, with no tags. For each environment, the user must
   test a non-master environment job with no AWS credentials or AssumeRole step:
   GitHub must reject it **before starting** a runner and obtaining an environment
   OIDC token. Also confirm a master job can pass the environment gate. Stop the cutover
   if either readback or enforcement check fails; leave IAM unchanged. Offline
   locked-provider tests prove configuration, not live enforcement. AWS sees
   environment subjects, not the original ref. If environment trust is already
   active while a gate is unprotected, the user must first disable that IAM trust;
   pausing only the two deployment workflows is not a security boundary.
3. **Activate IAM environment trust only after both gates pass.** Review/apply
   `infra/spacelift` to wire `drumrollworld_tools_github_actions_broker_role_arn`
   into the existing repository configuration stack; keep its full run held until
   the producer applies below complete. Use a user-approved staged change/run when
   the infrastructure branch is not yet on master. Then review/apply TOOLS: retain
   the existing OIDC provider and OConnorDev broker, restrict that broker to only
   `oconnordev-production` and OConnorDev's deploy role, and create the dedicated
   DrumrollWorld environment broker with only its own AssumeRole target.
   Inspect/import existing out-of-state resources first. Next review/apply
   `drumrollworld`: trust only the dedicated DrumrollWorld broker and remove the
   obsolete repair GetObject grant. Review PRODUCTION's role: its exact existing
   OConnorDev broker principal stays unchanged. No hosting resources/runtime/CSP/
   compiler changes belong in this cutover.
4. **Apply the full repository-configuration stack** only after producer outputs
   are available. Before applying, reconcile/import both bootstrapped environments
   at `github_repository_environment.site["oconnordev-production"]` and
   `github_repository_environment.site["drumrollworld-production"]`, and their
   recorded master policies at the corresponding
   `github_repository_environment_deployment_policy.master["<environment>"]`
   addresses, using the locked provider's documented import IDs. Require a plan
   preserving both environments and their master-only policies, not replacing or
   temporarily removing protection. Create
   `DRUMROLLWORLD_TOOLS_GITHUB_ACTIONS_BROKER_ROLE_ARN` from the new output; retain
   all five existing variables and their state addresses. Inspect/import any
   out-of-state variable rather than replace. Dedicated provider App permissions
   must be approved by the user; environment management requires its repository
   Environments write permission. Never borrow the Hermes App/PAT or broaden it
   automatically.
5. Read back both environment gates again and broker/deploy-role trusts/permissions;
   require exact repository/environment subjects and single-site targets. Stop
   if either environment lost its master-only protection during adoption.
6. Merge/re-enable workflows only after those checks. Verify same-run artifact
   upload/download, SHA256 verification before credentials, current-master gate,
   successful per-site role chain/publication/invalidation, and public metadata.

Rollback: pause workflows, review the intended trust/environment changes and
apply them as a user-owned operation, then merge a compatible workflow. Reverting
only IAM or only workflow subjects strands deployments. Application rollback is
a reviewed revert committed to master, not a rebuild of a stale queued run.

## Static-site root/module split

Before applying the new resume root or refactored production configuration, follow [the mandatory owner-operated state handoff](../static-site-state-migration.md). The existing administrative stack is `oconnordev`; the new resume stack is **`oconnordev-resume`**, root `infra/aws/oconnordev`. Do not reuse or relocate the administrative stack. Production keeps the shared zone, certificate and DNSSEC resources used by the Hermes endpoint. Both workloads consume explicit production outputs. Default-false guards intentionally block ordinary plans until the handoff is complete.
