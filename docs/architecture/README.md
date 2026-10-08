# Architecture

## Account and stack boundaries

The account map in `infra/aws/accounts.json` is the sole repository source for cross-account IDs and the Organizations ID. A stack uses `aws_caller_identity.current.account_id` for its own account; provider assume-role configuration reads its own ID from the same file because provider blocks cannot refer to OpenTofu data sources. Account IDs are deterministic, so they are not passed as Spacelift stack outputs. Only generated resources create cross-stack output references.

`general` owns Organizations and management-account identity/delegation. `security` owns centralized audit storage and the security-account AgentCore gateway. `tools` owns the shared Cognito-protected gateway and its GitHub, AWS, and Spacelift targets; OpenTofu resource and service labels remain Hermes-specific. `production` owns the public MCP endpoint; `drumrollworld` owns the static site.

## Audit architecture

`general` owns the organization CloudTrail trail. `security` owns the CloudTrail and AWS Config destination buckets, their explicit S3 bucket policies, the Config organization aggregator, and the security-account gateway. Member-account Config recorders deliver to the central Config bucket. The trail and bucket policy intentionally avoid a reverse stack dependency: the trail uses the bucket name as configuration, while the bucket policy constructs the trail ARN from the account map.

The bucket policies remain explicit policy documents attached directly to `aws_s3_bucket_policy` resources. Keep their principals, account conditions, and service conditions directly reviewable.

## AgentCore trust boundaries

`tools` owns one Cognito-protected AgentCore Gateway, one execution role, and the ENFORCE policy engine. Cognito client-credentials authentication establishes the machine caller; Cedar policies authorize target-prefixed action names. Shared gateway and authentication resources are in `gateway.tf` and `gateway-auth.tf`; target-specific credentials, target definitions, and Cedar rules are in `target-github.tf`, `target-aws.tf`, and `target-spacelift.tf`. GitHub PAT and Spacelift credentials remain separate from gateway-wide IAM.

The security-account gateway is a separate AWS_IAM trust boundary. Its resource policy admits the Hermes gateway role; its execution role's explicit read-deny policy remains directly inspectable. It does not use the Hermes OAuth Cedar engine.

## GitHub Actions site deployment

Both static-site workflows authenticate with GitHub OIDC to the TOOLS broker,
then assume separate site-scoped deploy roles in PRODUCTION. The broker trusts
only this repository’s `master` subject and may assume exactly those two roles.
Each role trusts only the broker and targets its own bucket/distribution.
`production` owns the OConnorDev site role; `drumrollworld` owns the DrumrollWorld
role. Generated DrumrollWorld outputs reach the GitHub repository-configuration
stack through its own dependency. Both apps use locked Biome lint/format checks.
DrumrollWorld additionally builds a locked npm/esbuild release with self-hosted
Three.js, Globe.gl and KTX2 decoder JS/WASM. Its S3/CloudFront origin serves the
complete runtime dependency bundle; no external module CDN is needed.
See [DrumrollWorld deployment](../runbooks/drumrollworld-deployment.md) for the
one-time apply order, master-only deployment gates, and image preservation.

## Stack dependency order

`general -> security -> tools -> production`. `security` waits for management-account delegated-administrator setup. TOOLS consumes the generated security gateway URL and ARN. PRODUCTION consumes the generated TOOLS outputs used by its workloads. Those generated values retain explicit Spacelift dependency references; deterministic account IDs and role names stay file-based cross-account references. Audit destination buckets live in `security`, while the organization trail is owned in `general`; first creation and enablement follow [`docs/runbooks/infrastructure-bootstrap.md`](../runbooks/infrastructure-bootstrap.md).
