# Runtime integration contract (not deployed)

This is the narrow **HTTP MCP-server target**, not a Lambda event tool target. It reuses upstream `MicrosoftGraphServer.createMcpServer`, tool handlers, `GraphClient`, and `AuthManager`/MSAL; it does not start the stock CLI or implement Graph APIs. Internal upstream hooks are contract-tested and must not float.

## Pins / build

- Actual package `@softeria/ms-365-mcp-server@0.166.0`, upstream git `675b82198701b9565ab3cdd836d1a2c7aac4f8c9`.
- npm integrity `sha512-15wBe9wbCbqyJAHL2gxJrz5fS9bGwvKYB4HHAVB4nhIr8PaVKsv7mSdnv70u7bGkLNbABk1E+rPAFIGU5M3b7g==` (also enforced by lock).
- `package-lock.json` locks the full dependency tree. Install only with `npm ci --ignore-scripts --omit=optional --no-audit --no-fund`.
- Dockerfile ARM64 base and adapter **platform manifest bytes** were fetched from Docker Registry / public ECR and their SHA256 verified. Node `22-bookworm-slim`: `sha256:b20fe038d9592822dd534600a1ddf467e985178aa3fed60ec441a056c2cc45bd`; adapter `0.9.1`: `sha256:cd0ad9539cbf223feb1cabd8f4deb7064b6270f185614274b940a36590cdc8f9`.
- `npm test`; `docker build --platform linux/arm64 -t owner-mail-runtime .`. Docker CLI exists here but daemon is unavailable; ARM64 build/run is **not verified**, and must gate deployment. No daemon was installed.

## Required infrastructure settings

Runtime binds **127.0.0.1:8080** only. LWA buffered HTTP with `/health`, using the pinned 0.9.1 release's supported `AWS_LWA_READINESS_CHECK_MIN_UNHEALTHY_STATUS=201`; its environment defaults match IaC. The controlled readiness route returns only 200 or 503, so only 200 is healthy (redirects and errors are unhealthy). `AWS_LWA_READINESS_CHECK_HEALTHY_STATUS` is not supported by that release and must not be used. `/health` returns 503 until the configured durable cache yields an owner token; it does not call Graph. All other paths except POST `/mcp` return 404 (GET `/mcp` = 405); no OAuth, auth helper, profile, attachment, sample or native HTTP routes are mounted. JSON stateless MCP; no session ID/SSE affinity. Invalid tools/arguments are rejected before secret read.

Expose **every URL path through AWS_IAM only**, with an explicitly authorized gateway caller and no NONE/public alternate route. Local loopback is not an authentication mechanism. Set reserved concurrency **1** and ensure **no other writer** (old function/version/alias, bootstrap process, or rotation job) can use this cache concurrently. The in-process mutex spans load, silent refresh, full-cache save, exact version readback and tool execution; it is not a distributed lock. Stop bootstrap/other writers before enabling runtime. This implementation must not be deployed without those infrastructure invariants.

Runtime role: `secretsmanager:GetSecretValue` and `secretsmanager:PutSecretValue` on **exact SECRET_ARN**, plus narrowly configured logging if needed. No ListSecrets, DeleteSecret, account discovery, broad KMS or arbitrary secret access. Choose the AWS managed Secrets Manager key unless a separately reviewed specific CMK policy is needed; encryption at rest is provided by Secrets Manager. Refresh rotation needs writes; read-only secret permission is insufficient.

Environment (nonsecret pins, no access/refresh tokens):

- `SECRET_ARN`: exact fixed Secrets Manager ARN.
- `M365_CLIENT_ID`: owner-approved personal-account application UUID.
- `EXPECTED_HOME_ACCOUNT_ID`: immutable exact consumer home account ID, suffix `.9188040d-6c67-4c5b-b112-36a304b66dad`.
- `EXPECTED_USERNAME`: optional additional username pin.
- Standard AWS region/runtime role configuration; LWA variables as Dockerfile. Upstream MS365_MCP variables are cleared and replaced by fixed security settings, not honored as extension hooks.

Use Lambda timeout greater than the wrapper's **15-second entire request deadline** (including secret operations, queue, refresh, body read and serialization), and below the independently verified gateway/client timeout with margin. AWS SDK maxAttempts=1; upstream Graph retries=0 and headers timeout=10s; total response body <=1 MiB (including error bodies and stalled-body deadline). MCP request <=16 KiB. No mailbox/auth logging: upstream Winston transports cleared, logger silent, audit disabled, MSAL logger no-op, errors sanitized. Keep infrastructure log retention finite. Actual cold-start timing/gateway budgets remain unverified.

## Durable cache format / consent boundary

SecretString is UTF-8 JSON <=64 KiB:

```json
{"version":1,"homeAccountId":"<exact immutable owner pin>","cache":"<full MSAL tokenCache.serialize() string>"}
```

`cache` must be a genuine full MSAL cache from an independently authorized owner bootstrap, **not** a fabricated Account record or an access-token-only blob. Exactly one Account with the consumer tenant ID above; all cached credentials must match the same home account/client ID and a known MSAL environment alias (`login.microsoftonline.com` or `login.windows.net`). Only allowed scope metadata; missing/corrupt/wrong-owner cache fails closed. No local token/cache/key copies or interactive bootstrap in runtime. New AuthManager instance per transaction prevents warm-token fallback after deletion; cache changes persist before a successful tool response and exact saved VersionId is read back. Missing/failed readback fails the request even if refresh succeeded. Secrets Manager version churn/quotas must be considered during real onboarding/load testing; no background refresh job is installed.

**No new consent was performed.** A separate owner-approved bootstrap must disclose Graph delegated **Mail.Read** (mail body reading) and **User.Read** (own basic profile), plus standard **openid**, **profile**, **offline_access** (identity and refresh persistence). Authority is fixed `https://login.microsoftonline.com/consumers`; no application roles/client credentials/OBO. Extra Graph scopes/roles rejected; runtime does not silently request broader scopes or select another account. Token expiry and returned account/scope metadata checked; Graph still verifies actual tokens. Optional JWT metadata checks are not signature verification. Bootstrap tooling is intentionally not supplied here; do not paste credentials into chat/config/IaC/state/CI.

## Stable catalog

`tools-manifest.json` is the strict schema source for infrastructure/adapter generation. Five names only; actual upstream camelCase `messageId` / `mailFolderId`. `top` 1..50 (default 10), `skip` 0..500; IDs 1..512 `[A-Za-z0-9_=-]`. Only message collections accept search (1..200 simple characters, wrapped in a single literal quoted query; no KQL operators/quotes/colon) and `orderby` (`receivedDateTime asc|desc`). Search cannot combine with skip/orderby. No filter, expand, user/account, arbitrary URL/method/body/headers, caller projections, cursor or auto-pagination. Fixed selects; `get-mail-message` includes body. No attachments/MIME. Graph destination/method/path/query keys are checked again below tools. `@odata.*` metadata including nextLink is removed; automatic pagination disabled regardless of provider nextLink. Use bounded skip on non-search collections instead; search has no continuation support in this pilot.

## Evidence and remaining gates

Synthetic tests start actual SDK HTTP transport and pinned upstream registration/GraphClient; probe all five tools, strict catalog, negative routes/arguments, malicious nextLink, request GET/projection, byte/deadline bounds, warm missing-cache failure, serialized refresh/save/readback and real MSAL silent refresh with synthetic token endpoint responses. No real credentials, live Secrets Manager, Microsoft sign-in/mail reads, deployment or commits occurred. Still required: actual ARM64 image build/run, deployed IAM positive/negative probes for every path, real owner-authorized bootstrap/consent, refresh/revocation validation, Secrets Manager quota behavior and cold-start/deadline measurements. Do not label this deployed or production-verified.
