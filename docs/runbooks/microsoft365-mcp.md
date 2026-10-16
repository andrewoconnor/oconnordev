# Microsoft365 personal-mail MCP: owner rollout, verification and rollback

## Status and boundary

**Activation configuration prepared for owner review/apply; runtime not yet live.**
The shared `oconnordev-tools` repository, publisher role and cache metadata bootstrap
are applied. The owner reports successful OAuth consent/cache bootstrap with the helper's
exact-version write/readback verification; this preparation has not independently
read that secret, refreshed credentials or called Graph. The exact nonsecret inputs
provided by the owner are now the TOOLS variable defaults:

* `microsoft365_runtime_enabled = true` (desired state on owner apply, not live status)
* `microsoft365_owner_home_account_id = "00000000-0000-0000-592d-43aab53672fd.9188040d-6c67-4c5b-b112-36a304b66dad"`
* `microsoft365_client_id = "084a3e9f-a9f4-43f7-89f9-d229cf97853e"`
* `microsoft365_image_digest = "sha256:c70a21d96fb7395455a638f76166c94180b28a79dd4819dc9c55f3a3d89998f1"`

Preserve the MSAL homeAccountId exactly, including its zero-prefixed UID; it is not
an email, inferred object ID or placeholder to repair. The published image is
`421680664125.dkr.ecr.us-east-1.amazonaws.com/oconnordev-tools@sha256:c70a21d96fb7395455a638f76166c94180b28a79dd4819dc9c55f3a3d89998f1`.
Verified master image workflow
[38816865741](https://github.com/andrewoconnor/oconnordev/actions/runs/38816865741),
publish job [116703905646](https://github.com/andrewoconnor/oconnordev/actions/runs/38816865741/job/116703905646),
succeeded with an actual push and matching ECR manifest readback for tag
`microsoft365-d00b116d0703403ee46e7db862d10cb47a0504c6-38816865741-1`.
That is publication evidence, not deployed Lambda or mailbox/runtime proof.
Runtime image inputs are unchanged since publication (subsequent owner-helper
verification-URL changes are outside the image); no new image build is required.
No secret value read/write/migration, mailbox request, Hermes config change, reload
or legacy Outlook cutover is authorized by this activation preparation. Adapter
rollout stays disabled. TOOLS remains on `master` with
`autodeploy=false`; only the owner may approve/apply reviewed plans. Existing live
AWS SDK reachability through the SECURITY gateway does not grant TOOLS access.

The package is `@softeria/ms-365-mcp-server@0.166.0`, upstream commit
`675b82198701b9565ab3cdd836d1a2c7aac4f8c9` (not an Entra organization connector).
The runtime wraps that upstream rather than implementing a second Graph client.
One delegated **personal consumer** identity is pinned by nonsecret MSAL
`homeAccountId`. Consent, app registration and initial cache bootstrap are a
separately authorized owner operation, using the consumers authority; never
client-credentials Graph access, organizational tenant fallback or first-account
selection. Owner should approve the actual scopes: Mail.Read, basic own identity
(User.Read plus MSAL OIDC defaults), offline_access. No auth/profile tools exposed.

Path: existing Cognito JWT `hermes-mcp/invoke` → existing shared Cedar engine in
ENFORCE mode → target **microsoft365** → `GATEWAY_IAM_ROLE` SigV4 (`service=lambda`,
`region=us-east-1`) → AWS_IAM Function URL `/mcp` → arm64 container, Lambda Web
Adapter, filtered upstream. This is an MCP-server target with listing_mode DEFAULT,
**not** AgentCore's native Lambda event-dispatch target. No gateway, authorizer,
client, OAuth scope or shared engine replacement.

Exactly these native tool names (no hyphen/camelCase normalization):

* `list-mail-messages`
* `get-mail-message` (`messageId`)
* `list-mail-folders`
* `list-mail-child-folders` (`mailFolderId`)
* `list-mail-folder-messages` (`mailFolderId`)

The wire action is `microsoft365___<native-name>`. No current adapter name collides,
so native names remain client-visible (no extra client namespace). The adapter
continues exposing its existing 23 tools by default; explicit temporary rollout
adds five. Cedar grants only those exact actions to AgentCore::OAuthUser with the
existing scope-tag check, following Spacelift's established principal model. Exact
scope admission remains the existing JWT authorizer's responsibility. Argument
bounds/unknown-key rejection, collection paths, one pinned consumer identity,
pagination and request/response limits are enforced by the runtime's strict
schemas and wrapper, not claimed as Cedar semantic guarantees. No generic get,
batch, write, arbitrary URL/header, auth, profile, calendar or users endpoints.

## Independent trust and persistence

**Activation privacy gate:** the owner explicitly approved disabling the shared
Gateway APPLICATION_LOGS delivery through separate IaC PR #118, now merged and
applied. TOOLS run `01M50PH738EP65ZF66HKX7CZMT0` finished `FINISHED` with
**0 add, 0 change, 1 destroy** and the managed delivery removed from state.
The privacy apply gate is cleared on that state/apply evidence, not a claim of
independent direct AWS enumeration or end-to-end logging proof. See
[Gateway log privacy](gateway-log-privacy.md) for retained historical seven-day
expiry and remaining metadata-only checks. OAuth/cache bootstrap is now
owner-reported complete; runtime apply and the separate activation proofs remain
outstanding. The desired enabled configuration does not itself clear those gates.
Runtime log suppression does **not**
suppress Gateway logs, and disabling Gateway delivery does not suppress runtime
or other logs. No end-to-end no-mailbox-logging guarantee or retroactive purge is
claimed; this runbook does not itself change shared observability or enable mail.

* Gateway role: only InvokeFunctionUrl conditioned on FunctionUrlAuthType=AWS_IAM
  and InvokeFunction conditioned on InvokedViaFunctionUrl=true, for this exact
  function ARN. It is not granted the consumer cache ARN; the existing gateway
  secret-read deny excludes this cache from its approved credentials.
* Runtime role: GetSecretValue and PutSecretValue for **one** fixed cache secret,
  plus CreateLogStream/PutLogEvents for its own finite-retention log group only.
* Publisher role: ECR push/readback on only the shared `oconnordev-tools` repository;
  GetAuthorizationToken requires Resource `*`. No Lambda update, PassRole, secret
  access, infrastructure apply or gateway privilege. The role can publish **any
  tag** in this repository, including future targets' tags. The `microsoft365-`
  prefix is a collision-avoidance convention, **not an authorization boundary**:
  ECR IAM cannot enforce an image-tag prefix for these push permissions. Sharing
  the repository shares the publisher content-trust boundary; review that risk
  explicitly before adding other publishers or targets.
* Function URL uses AWS_IAM. No public resource allow, wildcard public principal,
  CORS, unauthenticated alternative or forwarded Graph bearer authority. In the
  same account, these identity allows suffice. They are **not absolute exclusive
  access**: another same-account principal with identity grants can invoke too.
  A resource-policy allow for the gateway would not deny those identity grants.
  Review existing IAM/SCP permissions before live proof; do not present an allow
  as a restrictive deny boundary.
* ECR Lambda service pull policy is limited to this exact function SourceArn.
  Sharing the repository does not authorize future functions: extend the single
  repository policy explicitly with reviewed exact SourceArns for future targets,
  never a function-name wildcard. Function, runtime/publisher role, cache secret
  and gateway target names remain Microsoft365-specific.
  Repo and roles and secret metadata bootstrap regardless of activation; function,
  URL, runtime grants/logs, invoke grant, target/catalog and Cedar permits are
  gated together by `microsoft365_runtime_enabled`. The reviewed activation default
  is now true; explicit false retains bootstrap-only/rollback behavior.
* Reserved concurrency **1**, plus the runtime transaction mutex, serialize cache
  refresh/load/save/readback. No other function/version/client may write the cache;
  exclude owner bootstrap while active. Revocation/missing state must fail closed
  even in a warm environment. Credentials live only in Secrets Manager/MSAL memory;
  filesystem/log scratch is ephemeral. No provisioned concurrency, VPC/NAT,
  persistent worker, new Cognito setup or paid KMS key.

## Staged owner procedure (no automatic applies)

1. Bootstrap is already applied: shared ECR, repository policy, roles, empty
   cache metadata and TOOLS additional project globs. Review the exact proposed
   head and secretless checks for subsequent changes; provider locks remain AWS
   **6.66.0**. The owner now reports identity/cache bootstrap complete; do not
   rerun the empty-secret helper or introduce a competing cache writer.
   No secret-version resource exists; no secret values may enter
   tfvars, Spacelift variables, state, outputs, plans, CI or docs.
2. Review `microsoft365_bootstrap` output (only repository URL, publisher-role ARN,
   secret ARN). The shared repository is `oconnordev-tools`
   (`aws_ecr_repository.tools_images`), with URL
   `421680664125.dkr.ecr.us-east-1.amazonaws.com/oconnordev-tools`.
   The repository and role are in TOOLS, us-east-1, not SECURITY.
   The obsolete bootstrap publication-variable dependency is removed. Publication
   is allowed only for `master` push or `workflow_dispatch`, after the check job
   succeeds; PRs and feature-branch manual dispatch cannot acquire credentials.
   The old repository variable is unused and may optionally be removed by the
   owner in GitHub settings; this cleanup does not change repository settings.
   No GitHub Environment is required by this role's trust. The trust pins
   aud=sts.amazonaws.com and exact
   `repo:andrewoconnor/oconnordev:ref:refs/heads/master`. This proves repo/master,
   **not the workflow filename**: AWS does not support a job_workflow_ref condition
   here. Protect master and review all workflows able to request OIDC. A custom
   GitHub OIDC subject template can be a separate future trust change, not an
   invented workflow-identity guarantee or an uncreated environment gate.
3. On reviewed master, the image workflow publishes on matching push events or
   manual dispatch. **This activation changes only TOOLS defaults, offline tests
   and this runbook; it does not change runtime image inputs or deploy Lambda.**
   The verified run/digest is recorded above. PR/feature jobs have no AWS/OIDC credentials.
   The native arm64 build creates a single image without provenance
   indexes/attestations, runs secretless runtime tests (including real synthetic
   HTTP) inside that image (tests bind-mounted read-only; runtime modules and
   dependencies are the image bytes), saves it once and hashes its archive. Master publication
   downloads and verifies the same archive/image ID and compares **fresh master
   application inputs before credentials**. It loads/pushes those tested bytes,
   never rebuilds them. Dedicated ECR-only OIDC credentials are acquired only in
   publish. Tags use `microsoft365-<commit>-<run-id>-<run-attempt>` so different
   targets and reruns do not collide in the immutable shared repository. Future
   targets must choose their own prefix; prefixes are not IAM isolation. Digest
   is read back from `oconnordev-tools` and compared with docker push output.
   Capture the actual `repository@sha256:...` from job summary; never use `latest`
   or the synthetic fixture digest. No Lambda deployment occurs in workflow.
4. For first-time bootstrap only, separately authorize owner app/consumer consent and **new** serialized cache
   bootstrap using the [reviewed owner-only helper](#owner-only-consumer-consent-step-1).
   Do not read/copy the current local Outlook token/cache/key. Keep runtime disabled;
   stop all competing writers. Set only its verified nonsecret identity/client pins
   and the separately verified published image digest in TOOLS inputs. The owner
   reports this step complete for the identity above; do not repeat it now.
5. Owner reviews the exact activation head and TOOLS plan with the four nonsecret
   defaults above. Inspect any existing stack/environment variable overrides:
   they take precedence over defaults and must not silently retain false/empty or
   different pins. No separate Spacelift environment-variable management apply is
   introduced. Only the owner approves/applies; `autodeploy=false` stays unchanged.
   Offline mock plans render one function, IAM Function URL, log group, runtime
   grant, gateway invoke grant, catalog trigger and target, plus five Cedar permits.
   This is a configuration inventory, **not a live plan resource-change count**;
   review the actual owner plan for adds/changes/replacements and unrelated drift.
   No secret-version resource, Gateway log delivery, shared-engine mode change or
   new infrastructure outside the existing gated feature is introduced.
   These map to runtime `EXPECTED_HOME_ACCOUNT_ID` and `M365_CLIENT_ID`; the fixed
   secret ARN maps to `SECRET_ARN`. LWA readiness is `/health`, whose final status
   is 200 or 503. Supported LWA 0.9.1 setting MIN_UNHEALTHY_STATUS=201 rejects
   every final status above 200 (including redirects/404); the similarly named
   HEALTHY_STATUS variable is not supported by that release.
   The image must exist before Lambda creation, and cache must be valid before
   AgentCore performs tools/list. During the owner's apply/target discovery,
   readiness performs silent authentication and may refresh/persist the MSAL cache;
   do not mistake this for a metadata-only apply or run a competing helper. This
   preparation does not execute that authentication. Target and permits activate together; resource
   dependencies grant gateway URL invoke before registration and create permits
   only after action catalog exists. Verify target READY/SYNCHRONIZED and all five
   policy creations. A changed image/manifest triggers target catalog replacement;
   inspect live catalog after replacement, not just successful deployment status.
   No placeholder digest is provided in deployment examples.
6. Verify readback in TOOLS with the owner's approved identity: image digest,
   arm64, reserved concurrency=1, AWS_IAM Function URL, exact runtime/invoke IAM,
   secret metadata only, target MCP endpoint/credential mode and five exact Cedar
   actions under existing ENFORCE engine. Measure actual ARM64 cold start/refresh
   versus caller deadlines. The function timeout is 25 seconds; the adapter's
   read timeout is 15 seconds. Cold starts may exceed that client budget: an actual
   end-to-end timing proof is a gate, not an assumption or reason to enable warming.
7. Deploy adapter bytes **after** target/policies/catalog proof. Keep its rollout
   env unset/false in the existing registration. Start a separate, temporary stdio
   adapter process/registration with the same approved Cognito mechanism and only
   `HERMES_AGENTCORE_MICROSOFT365_ENABLED=true` added; do not hand-edit the manifest
   to toggle rollout. Exact lowercase `true`/`false` only; other values fail closed.
   Do not expose/read consumer cache to this adapter. No persistent Hermes edit or
   reload is authorized in this implementation.
8. Explicitly authorized live verification: obtain the exact existing scope;
   initialize and exhaust tools/list; require baseline plus exactly five mail tools
   (28 total), unchanged existing tool names and no duplicates. Make one bounded
   `list-mail-folders` probe (small top) without logging private response data.
   Check wrong/missing JWT scope/identity, unsigned URL, direct InvokeFunction
   without URL context, unlisted tool, arbitrary URL/header/expand/unknown args,
   malformed/unsafe IDs, oversized top, cross-collection pagination and mismatched
   homeAccountId all deny at the appropriate boundary with no unintended Graph
   request. Use only synthetic denial fixtures where a test would otherwise expose
   or mutate real cache. Verify gateway still cannot read consumer secret and the
   publisher cannot invoke/update Lambda or read secrets. Scope and policy tests
   must be performed at gateway too, not solely adapter filtering.
9. Only after all gates pass may the user authorize production adapter enable and
   client cutover. Keep the local Outlook connector unchanged throughout these
   stages. Removing old config/cache or restarting Hermes requires separate explicit
   approval; disabling a config reference does not revoke an upstream credential.

## Owner-only consumer consent (step 1)

**Historical bootstrap procedure, not an instruction to rerun now.** The helper is
merged and the owner reports successful verified cache persistence. No device
flow was started by this activation preparation. For any future bootstrap, require
separate owner approval and an absent runtime/empty secret as enforced below.
This is the same *permission boundary* as the local read-only Outlook setup, but a
fresh consent/session: it never imports the old connector's cache or key. It uses
public client **084a3e9f-a9f4-43f7-89f9-d229cf97853e**, consumers authority
`https://login.microsoftonline.com/consumers`, and only:

| Scope | Purpose |
| --- | --- |
| `Mail.Read` | Delegated reading of the signed-in owner's mail |
| `User.Read` | Basic own identity/profile |
| `openid` | Sign-in identity |
| `profile` | Basic identity claims |
| `offline_access` | Refresh token for later unattended read-only calls |

MSAL includes the last three OIDC scopes; the helper's synthetic endpoint test
checks the exact outgoing scope set. No application permissions, mail writes,
Graph `/me` call, mailbox request, token export, client secret, local cache
persistence, or scope-broadening fallback. A different public app requires separate
review and explicit `--client-id <UUID>` selection; it is disclosed before consent.
The client ID's availability/consent eligibility is not proven by offline tests.

Use **the owner's AWS CloudShell**, opened in **TOOLS account `421680664125`**,
region **`us-east-1`**. This is **not Google Cloud Shell**, not a Hermes terminal,
not SECURITY, and not a request to provide AWS keys to Hermes. Verify the console
account and actual shell Node version. Use Node **22 or newer**; if unavailable,
stop and arrange an owner-approved Node installation rather than running curl/bash
or unpinned npx. Do not enable shell tracing, terminal recording, debug logging or
paste console output containing device codes/credentials into chat.

After merge, from an owner-controlled checkout (fresh clone shown; if it already
exists use a clean reviewed master worktree instead):

```sh
git clone https://github.com/andrewoconnor/oconnordev.git
cd oconnordev
git switch master
git pull --ff-only origin master
git status --short
git rev-parse HEAD
node --version
npm --version
```

Compare the checkout HEAD and helper/lockfiles with the reviewed merged version
before proceeding; do not run the draft branch or an unexpected changed tree.
From that repository root install **both** locked dependency scopes (the helper
imports the production envelope validator from the runtime, whose relative imports
resolve against runtime dependencies):

```sh
npm ci --prefix infra/tools/lambdas/microsoft365_mcp --ignore-scripts --no-audit --no-fund
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

The helper lives outside the Lambda build context under
`scripts/bootstrap/microsoft365/`, so the runtime Dockerfile's `COPY *.mjs` cannot
ship the device-login CLI. The helper does not change runtime deployment switches;
this separate activation configuration changes only the desired TOOLS defaults.
Offline tests use mocked AWS clients and real pinned MSAL with a synthetic token
endpoint; they prove envelope interoperability, not live app eligibility, AWS
permissions, consent, stored identity or end-to-end runtime activation.
The dedicated `microsoft365-bootstrap.yml` PR/push workflow tests the helper with
Node 22 and both locked dependency scopes, without AWS credentials/OIDC, Docker,
or running the owner CLI. `mise run test:microsoft365-bootstrap` runs the same
secretless suite and is also included in the existing `mise run test` aggregate.

## Rollback and recovery

First disable Microsoft365 on the adapter (unset rollout env or `false`) and return
clients to unchanged legacy Outlook; verify its existing catalog before removing
the remote target. Owner sets `microsoft365_runtime_enabled=false` and reviews/applies removal of
five permits, target, URL/function and runtime/invoke grants. Bootstrap ECR/roles
and recoverable secret metadata remain. To stop image publication, use an
owner-reviewed workflow change or disable the workflow in GitHub Actions; the old
bootstrap variable no longer controls it. Retain the last verified digest for a
reviewed rollback;
no mutable tags and no auto-pruning policy that could delete a needed rollback
image. Monitor retained ECR size and explicitly remove unused images only after
owner review across **all** targets using the shared repository; do not delete
active or rollback images for another target. No lifecycle/automatic tag cleanup
is configured. Cache corruption/consent revocation is fail closed: stop writers,
re-consent/rebootstrap separately, never fallback to another cached account or
force repeated refresh retries. Never restore an obsolete refresh-token cache over
new rotated state. Removing Lambda does not revoke Microsoft consent.

## Cost and local proof limits

Official pricing checked during implementation:
[Lambda](https://aws.amazon.com/lambda/pricing/) (arm64 first tier about
$0.0000133334/GB-s, $0.20/million requests),
[ECR](https://aws.amazon.com/ecr/pricing/) ($0.10/GB-month private storage),
[Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/)
($0.40/secret-month plus $0.05/10,000 API calls). Lambda's published free tier is
shared across the account and subject to eligibility/credits; do not assume it is
unused or that this workload is free. With no calls Lambda compute is not billed;
reserved concurrency is a limit, not provisioned capacity.

Illustrative **not measured** incremental month: one secret + 0.5 GB retained image
+ 1,000 calls at 512 MB/2 seconds + 3,000 secret API calls is about **$0.48** before
free tier, logs, network, shared Gateway/Policy/Cognito usage, CI and tax. Stored
images accumulate without lifecycle deletion; audit actual image sizes and call
counts. Existing shared services continue their own billing. No tens-of-dollars
always-on infrastructure is introduced, but this is not a total bill estimate.

Offline commands (no live apply):

```sh
mise exec -- python -m unittest discover -s agents/hermes/adapter/test -t agents/hermes/adapter -v
mise exec -- python -m unittest scripts.ci.tests.test_microsoft365_boundary scripts.ci.tests.test_microsoft365_image scripts.ci.tests.test_microsoft365_policy_rendering -v
mise exec -- tofu -chdir=infra/aws/tools init -backend=false -input=false -lockfile=readonly
mise exec -- tofu -chdir=infra/aws/tools validate
mise exec -- tofu -chdir=infra/aws/tools test
mise exec -- actionlint .github/workflows/microsoft365-image.yml
mise exec -- checkov -d infra/aws/tools --framework terraform
mise exec -- checkov -f .github/workflows/microsoft365-image.yml --framework github_actions
```

The isolated IAM-rendering test uses only synthetic fixed ARNs and a local plan
with provider validation/metadata/AWS credential requests disabled; no apply or
remote account. Mock root tests prove both activation gates and exact Cedar output,
not live SigV4 interoperability or mailbox authorization. Local Docker CLI exists
but daemon is unavailable: no local arm64 image/HTTP container proof is claimed.
The workflow requires that real image test before publication; owner must review
its successful result before activation. The published image run above is CI
container/publication evidence, not live OAuth, Lambda or mailbox verification;
none of those live activation tests has been executed by this preparation.
