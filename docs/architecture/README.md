# Architecture

## Account and stack boundaries

The account map in `infra/aws/accounts.json` is the sole repository source for cross-account IDs and the Organizations ID. A stack uses `aws_caller_identity.current.account_id` for its own account; provider assume-role configuration reads its own ID from the same file because provider blocks cannot refer to OpenTofu data sources. Account IDs are deterministic, so they are not passed as Spacelift stack outputs. Only generated resources create cross-stack output references.

`general` owns Organizations and management-account identity/delegation. `security` owns centralized audit storage and the security-account AgentCore gateway. `tools` owns the shared Cognito-protected gateway and its GitHub, AWS, Spacelift and Microsoft365 targets; OpenTofu resource and service labels remain Hermes-specific. `production` owns the public MCP endpoint and shared oconnor.dev zone, wildcard certificate and DNSSEC; `oconnordev-resume` owns the resume site (`infra/aws/oconnordev`); `drumrollworld` owns its static site.

## Tools-account Lambda sources

Lambda source packages owned by the TOOLS account live under
`infra/aws/tools/lambdas/`: `spacelift_session_token/` and `microsoft365_mcp/`.
The Microsoft365 Docker build context is the latter directory; owner bootstrap
entrypoints remain separately under `scripts/bootstrap/microsoft365/` and import
its envelope validator. The tools project root already covers both packages, so
no additional external-source Spacelift glob is required for them. Build context and owner helper remain separate from runtime activation.

## Thundermail native Lambda

`thundermail-runtime.tf` and `target-thundermail.tf` define an
ARM64 Rust native Lambda alongside, not replacing, Microsoft365. The existing
Cognito gateway invokes its exact ARN directly using `mcp.lambda` and inline
schemas, with three Cedar read permits. No Function URL/HTTP/LWA or Node.
The runtime alone may read the app-password secret. Terraform manages the secret
metadata, never the value.
Adapter opt-in uses `HERMES_AGENTCORE_THUNDERMAIL_ENABLED`, exposes `thundermail-`
names, and forwards exact underscore raw tools under `thundermail___`.

`infra/aws/tools/lambdas/thundermail_mcp/` builds a pinned provided.al2023 bootstrap container for
the existing shared ECR repository. Master CI publishes the image with the existing
ECR-only publisher. `thundermail_runtime_enabled` deploys it. Outlook Graph, Gmail readonly and local CalDAV remain
unchanged. See [the runbook](../runbooks/thundermail-mcp.md).

## Google Auth ownership

The administrative `oconnordev` stack owns the protected, autodeploy-disabled
native GCP stack/integration outside the AWS stack loop. `infra/gcp/google-auth`
contains project `adept-presence-510022-p7` (`693193037198`, `oconnordev-tools`),
manual WIF pool/provider, bootstrap service account, and additive Browser/read
memberships. Native Spacelift authentication is separate from the incomplete
manual WIF configuration. All managed objects have `prevent_destroy`; project,
pool/provider and service account use ABANDON. Billing, APIs, authoritative IAM,
impersonation and Gmail OAuth remain outside this root's scope.

Configuration and offline tests do not prove live reconciliation. Use the
[Google Auth runbook](../runbooks/gcp-google-auth-discovery.md) for exact identity,
provider preservation and owner plan gates.

## Audit architecture

`general` owns the organization CloudTrail trail. `security` owns the CloudTrail and AWS Config destination buckets, their explicit S3 bucket policies, the Config organization aggregator, and the security-account gateway. Member-account Config recorders deliver to the central Config bucket. The trail and bucket policy intentionally avoid a reverse stack dependency: the trail uses the bucket name as configuration, while the bucket policy constructs the trail ARN from the account map.

The bucket policies remain explicit policy documents attached directly to `aws_s3_bucket_policy` resources. Keep their principals, account conditions, and service conditions directly reviewable.

## AgentCore trust boundaries

`tools` owns one Cognito-protected AgentCore Gateway, one execution role, and the ENFORCE policy engine. Cognito client-credentials authentication establishes the machine caller; Cedar policies authorize target-prefixed action names. M2M access tokens have an explicit 60-minute validity; ID/refresh-token settings are not configured for this flow. The adapter caches the returned `expires_in` lifetime and refreshes with its existing 60-second skew, or once after a gateway 401; extending validity does not force periodic token requests when idle. Shared gateway and authentication resources are in `gateway.tf` and `gateway-auth.tf`; target-specific credentials, target definitions, and Cedar rules are in `target-github.tf`, `target-aws.tf`, `target-spacelift.tf`, and `target-microsoft365.tf`. GitHub PAT and Spacelift credentials remain separate from gateway-wide IAM.

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

`general -> security -> tools -> production -> {oconnordev-resume, drumrollworld}`. Both site workloads consume production's DNSSEC key ARN; resume also consumes the shared zone ID and wildcard certificate ARN. The zone/certificate remain in production for the Hermes endpoint. Site resources share the local `infra/modules/static-site` module. `security` waits for management-account delegated-administrator setup. TOOLS consumes the generated security gateway URL and ARN. PRODUCTION consumes the generated TOOLS outputs used by its workloads. Those generated values retain explicit Spacelift dependency references; deterministic account IDs and role names stay file-based cross-account references. Audit destination buckets live in `security`, while the organization trail is owned in `general`; first creation and enablement follow [`docs/runbooks/infrastructure-bootstrap.md`](../runbooks/infrastructure-bootstrap.md).
