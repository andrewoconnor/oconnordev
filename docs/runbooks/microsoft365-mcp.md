# Microsoft365 personal-mail MCP operations

## Architecture and identity

Microsoft365 mail access runs through AgentCore, not a local mail connector.
Source and Docker build context: `infra/aws/tools/lambdas/microsoft365_mcp/`.
The wrapper uses pinned `@softeria/ms-365-mcp-server@0.166.0`, upstream
`675b82198701b9565ab3cdd836d1a2c7aac4f8c9`, rather than a second Graph client.
See the [runtime contract](../../infra/aws/tools/lambdas/microsoft365_mcp/INTEGRATION.md)
for exact package/base-image pins, deadlines, envelope and argument schemas.

Path: Cognito JWT `hermes-mcp/invoke` → shared ENFORCE Cedar engine →
`microsoft365` MCP-server target → gateway SigV4 (`lambda`, `us-east-1`) →
AWS_IAM Function URL `/mcp` → arm64 Lambda/Web Adapter → filtered upstream Graph.
This is not the native Lambda event-dispatch target. Function URL IAM is not an
absolute exclusive-access deny: other same-account identities may have invoke
grants. Inspect effective IAM/SCPs before claiming caller exclusivity.

TOOLS nonsecret configuration pins:

* `microsoft365_runtime_enabled = true`
* `microsoft365_owner_home_account_id = "00000000-0000-0000-592d-43aab53672fd.9188040d-6c67-4c5b-b112-36a304b66dad"`
* `microsoft365_client_id = "084a3e9f-a9f4-43f7-89f9-d229cf97853e"`
* `microsoft365_image_digest = "sha256:c70a21d96fb7395455a638f76166c94180b28a79dd4819dc9c55f3a3d89998f1"`

Preserve the homeAccountId byte-for-byte, including the zero-prefixed UID.
The shared ECR repository is
`421680664125.dkr.ecr.us-east-1.amazonaws.com/oconnordev-tools`.
Configuration pins are not a fresh live deployment or mailbox proof.
Only the owner reviews/applies TOOLS plans; `autodeploy=false`.

## Catalog and authorization

Exactly five native names, routed as `microsoft365___<native-name>`:

* `list-mail-messages`
* `get-mail-message` (`messageId`)
* `list-mail-folders`
* `list-mail-child-folders` (`mailFolderId`)
* `list-mail-folder-messages` (`mailFolderId`)

The adapter rollout flag is `HERMES_AGENTCORE_MICROSOFT365_ENABLED=true`;
its code default is disabled. Only exact lowercase true/false is accepted.
Do not restore a local mail registration or place the cache in the adapter.
Cedar authorizes these exact actions for the existing OAuth principal/scope-tag
model. The JWT authorizer admits scope; runtime schemas enforce owner identity,
strict arguments, bounded collections and request/response limits. No arbitrary
URL/header, generic get/batch, write, attachment, auth/profile/calendar/user tools
or automatic pagination is exposed. Tool listing is not mailbox access proof.

## Privacy and persistence

Keep the [Gateway privacy boundary](gateway-log-privacy.md): no shared
APPLICATION_LOGS delivery, retained finite log-group expiry and native metrics.
Runtime suppression does not suppress Gateway or other logs.
No end-to-end no-mailbox-logging guarantee is made; delivery control is not a purge.

The gateway may invoke this Function URL, not read its cache. The runtime role
has GetSecretValue/PutSecretValue on one fixed cache ARN and bounded logging on
its own group. No secret values belong in IaC, plans/state, variables, outputs,
CI, chat or local copies. Reserved concurrency **1** and a transaction mutex
serialize load/refresh/save/exact-version readback; stop all competing writers,
including owner bootstrap. The mutex is not a distributed lock. Missing,
corrupt, wrong-owner or revoked state fails closed even when warm. Never fall
back to another cached account or overwrite rotated cache with an older copy.

The ECR-only publisher cannot deploy Lambda, PassRole, read secrets or apply IaC.
It can push any tag in the shared repository: `microsoft365-` is a naming
convention, not IAM isolation. Review shared content trust before adding targets.
The Lambda pull policy uses an exact function SourceArn, never a wildcard.
Image publication tests a real arm64 image, transports the same archive, verifies
its digest and master-input freshness before credentials, then reads back the
pushed ECR digest. No mutable latest tag, rebuild-in-publish or auto-pruning of
active/rollback images is allowed.

## Owner-only consumer bootstrap

Do not rerun bootstrap on an occupied cache or deployed runtime. OAuth consent,
cache replacement and live mailbox probes require separate owner approval.
For a genuinely empty bootstrap, use the owner's AWS CloudShell in TOOLS
`421680664125`, `us-east-1`, with Node/npm and a clean reviewed master checkout.
Do not enable tracing/recording or paste device codes, passwords or MFA into chat.
The public consumer client above uses
`https://login.microsoftonline.com/consumers` with only delegated `Mail.Read`,
`User.Read`, `openid`, `profile`, `offline_access`. No application permissions,
organizational fallback, client secret or cache import is permitted. Disclose
these exact scopes before consent; stop on a different client, scope or account.

From a clean, owner-controlled reviewed master checkout, install **both** locked dependency scopes (the helper
imports the production envelope validator from the runtime, whose relative imports
resolve against runtime dependencies):

```sh
npm ci --prefix infra/aws/tools/lambdas/microsoft365_mcp --ignore-scripts --no-audit --no-fund
npm ci --prefix scripts/bootstrap/microsoft365 --ignore-scripts --no-audit --no-fund
npm test --prefix scripts/bootstrap/microsoft365
node scripts/bootstrap/microsoft365/cli.mjs --help
```

Only after explicit owner authorization, start the interactive operation:

```sh
node scripts/bootstrap/microsoft365/cli.mjs
```

The helper uses **one shared AWS SDK credential-provider chain** for STS, Secrets
Manager and Lambda, all pinned to `us-east-1`; it does not mix an AWS CLI profile
check with a different SDK identity. Required owner privileges are STS
`GetCallerIdentity`, `lambda:GetFunction` on `hermes-microsoft365-mcp`, and
`secretsmanager:DescribeSecret`, `PutSecretValue`, `GetSecretValue` on exactly
`arn:aws:secretsmanager:us-east-1:421680664125:secret:/hermes/microsoft365/msal-cache-CnJLNM`.
No role/policy modification is performed; if denied, stop for a separately reviewed
owner permission decision. Do not give these privileges to the publisher/gateway.

1. It verifies TOOLS via STS and displays the IAM ARN, fixed region, client,
   scopes and exact destination. Metadata must show **no secret versions at all**
   (even an empty-string value is occupied), the secret must already exist, and
   Lambda `GetFunction` must return `ResourceNotFoundException`. A deployed but
   inactive/stopped function is rejected; denied/ambiguous checks fail closed.
2. Read the disclosure and type `YES` only if you approve consent plus the one
   secret write and have stopped **all** competing writers. Checks are repeated
   just before writing, but Secrets Manager has **no atomic empty-secret CAS**:
   exclusive-writer discipline remains an owner prerequisite.
3. Enter the displayed code directly at **https://microsoft.com/devicelogin**,
   choosing the intended personal Microsoft account. Never send the code, password
   or MFA response to Hermes/chat. Only the exact allowlisted HTTPS verification
   URI and code are printed, not Microsoft's arbitrary callback message. Stop if
   the consent screen requests anything beyond the disclosed scopes/client.
4. The helper creates a fresh in-memory MSAL 5.6.0 cache. It validates the sole
   consumer account, approved grants, refresh-token presence and token client/owner
   using the production `validateEnvelope`. It displays username, **MSAL
   homeAccountId** (not a locally inferred `oid`) and client. Type `YES` again only
   if it is your intended identity. No `YES` flags/noninteractive bypass exist.
5. It rechecks the metadata/runtime guards, writes a version-1 envelope once, and
   reads back **that exact returned version** for in-memory equality and validation.
   It prints only the nonsecret `microsoft365_owner_home_account_id` and
   `microsoft365_client_id` TOOLS inputs. Choose the latest separately verified
   published image manifest digest; the helper neither deploys nor enables runtime.

On failure no raw provider errors/stacks/token bodies are printed. A failed
write/readback can leave a version present; do not rerun to overwrite it or print
its value. Stop for owner recovery using metadata only. On cancellation after
Microsoft consent, no cache write occurs, but consent may already exist at Microsoft;
revocation is a separate owner action. Cache account removal and result-reference
clearing run on normal completion/failure, then the CLI exits; JavaScript garbage
collection is **not cryptographic memory zeroization**. No credentials are written
to the filesystem by this helper. AWS CloudShell/browser/platform security remains
the owner's trust boundary.

## Change and verification gates

1. Review exact-head tests, image digest and actual TOOLS plan. Inspect input
   overrides; source defaults do not override stack/context values. Require valid
   cache before target discovery and an existing image before function creation.
   Discovery/health may refresh and persist cache; it is not metadata-only.
2. Owner applies and verifies arm64 digest, reserved concurrency=1, AWS_IAM URL,
   exact runtime/invoke IAM, cache metadata, READY/SYNCHRONIZED target, five Cedar
   actions and ENFORCE status. A catalog/image change may replace the target;
   inspect its live catalog, not merely the apply status.
3. Deploy adapter only after gateway catalog/policies. Separately authorize
   bounded native reads and deny probes: wrong JWT/scope, unsigned/direct invoke,
   unlisted tools, unsafe arguments, owner mismatch and cache failures. Use
   synthetic fixtures where real cache mutation or disclosure would otherwise
   occur. Never log private mailbox responses. Verify publisher/gateway denials.
4. Measure cold-start/refresh end-to-end timing: function timeout is 25 seconds,
   adapter read timeout 15 seconds. Offline tests do not prove this budget or
   live authorization; do not enable warming to conceal an unverified deadline.

## Pause and recovery

Disable the adapter rollout flag and report mail unavailable; do not route to a
local connector. Preserve the working cache. Owner-reviewed
`microsoft365_runtime_enabled=false` removes the gated function/URL, grants,
target and five permits; bootstrap repository/roles and secret metadata remain.
Removing Lambda does not revoke Microsoft consent. Cache/consent recovery is a
separate owner operation: stop writers and review metadata, never repeatedly
refresh or overwrite an occupied secret. The helper intentionally rejects it.

Retain verified image digests for rollback. Shared ECR has no automatic lifecycle
cleanup; review all targets before removing images. Disabling image workflow
publication does not disable runtime. Monitor real image storage, secret API,
Lambda and shared gateway/log/CI usage; free-tier eligibility is not assumed.

## Offline verification

```sh
mise run test:microsoft365-bootstrap
mise run test:python
mise run test:opentofu-boundary
mise run workflow-lint
```

Synthetic MSAL/Graph/AWS fixtures and mocked plans establish source contracts,
not current live consent, cache identity, SigV4 enforcement, privacy or mailbox
availability. Only explicitly authorized real readbacks establish those results.
