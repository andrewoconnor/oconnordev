# Architecture

## Account and stack boundaries

The account map in `infra/aws/accounts.json` is the sole repository source for cross-account IDs and the Organizations ID. A stack uses `aws_caller_identity.current.account_id` for its own account; provider assume-role configuration reads its own ID from the same file because provider blocks cannot refer to OpenTofu data sources. Account IDs are deterministic, so they are not passed as Spacelift stack outputs. Only generated resources create cross-stack output references.

`general` owns Organizations and management-account identity/delegation. `security` owns centralized audit storage and the security-account AgentCore gateway. `tools` owns the shared Cognito-protected gateway and its GitHub, AWS, and Spacelift targets; OpenTofu resource and service labels remain Hermes-specific. `production` owns the public MCP endpoint and shared oconnor.dev zone, wildcard certificate and DNSSEC; `oconnordev-resume` owns the resume site (`infra/aws/oconnordev`); `drumrollworld` owns its static site.

## Google Auth project discovery ownership

The administrative `oconnordev` stack owns the separate
`oconnordev-gcp-google-auth` stack and its native Spacelift GCP service account in
`infra/spacelift/gcp-google-auth.tf`. It does not join the AWS managed-stack or
integration-attachment loop. The root `infra/gcp/google-auth` only reads the
existing project `adept-presence-510022-p7` and validates its expected number
`693193037198` and name `oconnordev-tools`; ACTIVE rejection is enforced by the
pinned Google provider's real data-source read. No Google resources are yet
managed or imported. The owner controls administrative merge/apply, obtains the
actual native account email and grants project-scoped `roles/browser` in Cloud
Shell. Cloud-platform token scope does not grant IAM permissions.

Native run-token availability, exact live read and billing association are
pending gates. A second owner-reviewed PR may import the project only after
those gates and a preservation-only plan. Both stacks disable autodeploy and
have Spacelift deletion protection. This path does not mount local federation
JSON, require a paid generic OIDC pool, modify the existing Gmail OAuth client
or MCP scopes, or remove manually created WIF resources. See the
[staged runbook](../runbooks/gcp-google-auth-discovery.md).

## Audit architecture

`general` owns the organization CloudTrail trail. `security` owns the CloudTrail and AWS Config destination buckets, their explicit S3 bucket policies, the Config organization aggregator, and the security-account gateway. Member-account Config recorders deliver to the central Config bucket. The trail and bucket policy intentionally avoid a reverse stack dependency: the trail uses the bucket name as configuration, while the bucket policy constructs the trail ARN from the account map.

The bucket policies remain explicit policy documents attached directly to `aws_s3_bucket_policy` resources. Keep their principals, account conditions, and service conditions directly reviewable.

## AgentCore trust boundaries

`tools` owns one Cognito-protected AgentCore Gateway, one execution role, and the ENFORCE policy engine. Cognito client-credentials authentication establishes the machine caller; Cedar policies authorize target-prefixed action names. Shared gateway and authentication resources are in `gateway.tf` and `gateway-auth.tf`; target-specific credentials, target definitions, and Cedar rules are in `target-github.tf`, `target-aws.tf`, and `target-spacelift.tf`. GitHub PAT and Spacelift credentials remain separate from gateway-wide IAM.

The security-account gateway is a separate AWS_IAM trust boundary. Its resource policy admits the Hermes gateway role; its execution role's explicit read-deny policy remains directly inspectable. It does not use the Hermes OAuth Cedar engine.

## GitHub Actions site deployment

Each static-site workflow authenticates with GitHub OIDC to its own
TOOLS environment-scoped broker (`oconnordev-production` or
`drumrollworld-production`), then assumes only its own site deploy role in
PRODUCTION. Each deploy role trusts its corresponding broker, not the other
site’s broker. `oconnordev-resume` (`infra/aws/oconnordev`) owns the resume
role/distribution outputs; DrumrollWorld owns its outputs. Both reach the
GitHub repository-configuration stack through their workload dependencies.

The check job checks out `github.sha`, runs locked builds, lint/format, app
tests and the actual-HCL CSP browser proof, then packages tested public bytes.
The deploy job checks out the same `github.sha` and downloads the same-run,
SHA-named artifact. It verifies the archive digest and validates app-scoped
freshness before AWS credentials: exact fetched master and tested commits
must agree on app, deploy scripts, shared build inputs, security proof and
site policy/module inputs. Infrastructure/docs-only successors may deploy
the preserved tested artifact; relevant input changes reject stale runs.
It never blindly checks out master or rebuilds untested bytes.

Each site has separate per-ref concurrency with active-run cancellation
disabled. Concurrency is not FIFO and may replace pending runs; neither it
nor freshness verification provides an atomic release switch. S3 publication
and CloudFront invalidation remain non-atomic. DrumrollWorld’s locked
esbuild release self-hosts Three.js, Globe.gl and KTX2 JS/WASM. Its CSP proof
uses checksum-pinned genuine upstream KTX2 fixtures and Playwright’s pinned
Chromium, not manually provisioned fixtures or production artwork.
See [DrumrollWorld deployment](../runbooks/drumrollworld-deployment.md).

## Stack dependency order

`general -> security -> tools -> production -> {oconnordev-resume, drumrollworld}`. Both site workloads consume production's DNSSEC key ARN; resume also consumes the shared zone ID and wildcard certificate ARN. The zone/certificate remain in production for the Hermes endpoint. Site resources share the local `infra/modules/static-site` module. The cross-state resume move is owner-reported complete (both stacks FINISHED with unchanged distribution and role); the [historical handoff](../static-site-state-migration.md) remains available, not a current migration prerequisite. `security` waits for management-account delegated-administrator setup. TOOLS consumes the generated security gateway URL and ARN. PRODUCTION consumes the generated TOOLS outputs used by its workloads. Those generated values retain explicit Spacelift dependency references; deterministic account IDs and role names stay file-based cross-account references. Audit destination buckets live in `security`, while the organization trail is owned in `general`; first creation and enablement follow [`docs/runbooks/infrastructure-bootstrap.md`](../runbooks/infrastructure-bootstrap.md).
