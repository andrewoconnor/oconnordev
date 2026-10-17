# Thundermail native Rust MCP — dormant delivery draft

## Scope and contract

Only `oconnor@thundermail.com` at certificate-verified `mail.thundermail.com:993`.
Outlook's Graph Lambda, Gmail read-only connector and local CalDAV are unchanged.
The three raw names are `imap_list_mailboxes`, `imap_search_messages`, and
`imap_get_message`. Hermes sees `thundermail-` followed by each raw name; native
AgentCore context contains `thundermail___` followed by the same raw name.
Unknown tools, aliases, host/account overrides and write/SMTP actions are denied.

This uses the existing gateway's native Lambda target and gateway IAM role:
`target_configuration.mcp.lambda.lambda_arn` and
`tool_schema.inline_payload` (AWS provider **6.66.0**). It is **not** MCP-over-HTTP,
a Function URL, API Gateway, Node wrapper, stdio bridge or Lambda Web Adapter.
AgentCore passes the argument map as the event, and tool identity in
`context.client_context.custom.bedrockAgentCoreToolName`. There is no JSON-RPC,
API Gateway envelope or `statusCode` response from the bootstrap.

Sources checked for this draft:
- [AWS native Lambda event/context contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
- [Provider 6.66.0 target example and schema](https://github.com/hashicorp/terraform-provider-aws/blob/v6.66.0/website/docs/r/bedrockagentcore_gateway_target.html.markdown)
- [Provider SchemaDefinition conversion](https://github.com/hashicorp/terraform-provider-aws/blob/v6.66.0/internal/service/bedrockagentcore/gateway_target.go)

**Schema limitation:** AWS SchemaDefinition only expresses basic types, properties,
required fields and descriptions. It cannot carry `additionalProperties:false`,
bounds, enum/default or nullable unions. IaC projects the three inline tools into
that vocabulary (cursor is optional string; omit it instead of sending null).
The runtime remains the validation authority. The adapter restores the independently
owned full strict `toolSchemas` in `thundermail-mcp-tools.json`; an offline test
requires exact equality with the runtime schema and parses discovery using the
real MCP SDK. This is not a claim of live gateway schema fidelity or response wrapping.

## Default-off boundaries and cost

Both `thundermail_secret_bootstrap_enabled` and `thundermail_runtime_enabled`
default **false**. Default plans create zero Thundermail resources. Secret bootstrap
is an independent, explicitly paid opt-in: metadata at exactly
`/hermes/thundermail/app-password`, 30-day recovery, **no secret version/value**.
The owner provisions/rotates a **fresh dedicated app password** separately; do not
copy a local Himalaya/mail credential. SecretString must be the strict versioned
object with `version: 1` and `password` (no other keys). Never pass the value into
Terraform, a build, a workflow, a chat or a command recorded in this repository.

Activation is source-blocked even under an enabled runtime flag. The dormant
resource definition additionally requires an immutable tested ECR manifest digest
plus exactly one secret
source: newly managed metadata, or an exact existing same-account us-east-1 ARN.
Runtime alone gets `GetSecretValue` on that ARN, no write/list privileges. Gateway
gets only `InvokeFunction` on the exact function ARN, never secret reads or URL
access. Role, logs, function, grants, catalog replacement, target and three exact
Cedar read permits share the runtime gate. Existing OAuth principal/scope and
ENFORCE engine remain unchanged. Disabling removes the Thundermail target and
permits together; it does not remove unrelated tools.

Use the shared `oconnordev-tools` ECR repository and existing ECR-only publisher.
Its role permissions do not gain Lambda updates, PassRole, secrets or apply rights.
Tag prefixes are collision conventions, not ECR IAM isolation. The existing
Microsoft pull grant is byte-equivalent while disabled; enabled it adds only the
exact Thundermail function ARN. No new repository, gateway, VPC, NAT or customer
KMS key. A serialized 128 MiB ARM64 Lambda scales to zero with finite 14-day logs.
Secret metadata, ECR storage/scanning, requests, execution, logs and the existing
gateway can incur charges; metadata opt-in is **not free**, even without mail calls.
No dollar estimate is asserted. Runtime memory/timeout still need ARM64 measurement.

## Build and offline verification

`infra/aws/tools/lambdas/thundermail_mcp/Dockerfile` uses one pinned ARM64 provided.al2023 image for
both build and runtime ABI. A checksum-pinned mise binary installs the Rust version
from the repository `mise.toml`. Cargo uses `--locked`, jobs=1. It compiles the native release binary as `/var/runtime/bootstrap`.
No Node/LWA, secrets or cloud credentials enter the build. OS build packages come
from AL2023 repositories; their versions are not fully hermetic. Publication uses
the **saved tested image**, not a supposedly identical rebuild.

```sh
# mise installs the pinned Rust toolchain from mise.toml.
# Reuse existing target/cache paths on constrained hosts; maintain >=300 MiB free.
mise install rust
export CARGO_TARGET_DIR=/path/to/existing/dedicated-target
mise run test:thundermail-rust
# Reuse a compatible isolated SDK interpreter if already available:
export THUNDERMAIL_SDK_PYTHON=/path/to/sdk-venv/bin/python
mise run test:thundermail-sdk
mise run test:opentofu-boundary
mise run test
```

With no SDK interpreter override, the SDK task creates a temporary isolated venv
with MCP 2.0.0, never global pip. Generic CI installs Rust through mise. `mise test` declares both Rust and SDK checks alongside
existing tests. Native ARM64 image CI separately performs locked Rust tests and
runs the exact production bootstrap through a synthetic Runtime API with invalid
inputs, then archives it. That smoke proves packaging/dispatch/fail-closed behavior,
**not successful mail reads**. This host has no Docker daemon; ARM64/container
execution is not claimed locally.

## Security gate

The lock pins rustls 0.23.46, including the current rustls advisory fixes, and
`aws-smithy-json` 0.62.7, which fixes
[GHSA-8ffr-xgwf-xj56](https://github.com/smithy-lang/smithy-rs/security/advisories/GHSA-8ffr-xgwf-xj56).
That release requires Rust 1.91.1, which mise pins.

## Publication and activation approval gates

A master run publishes the saved tested image to ECR after the ARM64 check job
passes. Before OIDC, the publisher verifies the archive hash and image ID and
confirms that fresh master has the same image inputs. It never rebuilds. After the
push, it reads back the ECR digest and compares it to the push output. Publication
does not update Lambda or apply IaC.

Activation is source-blocked by the constant
`local.thundermail_activation_ready = false` lifecycle precondition: setting
`thundermail_runtime_enabled=true` rejects every digest, including syntactically
valid arbitrary digests. Opening the gate requires a separate reviewed source
change, not a portal setting or Terraform input. Independent metadata-only
bootstrap plans remain valid.

Offline tests assert readiness rejection against production source. OpenTofu omits
failed-precondition resources/dependents, so full enabled-resource/IAM assertions
also run in an isolated test-only source fixture that overrides the local while
retaining all lifecycle preconditions. This is not a production input or deployment
path. Schema-free Cedar evaluation checks scoped policy decisions only; live
AgentCore policy/schema validation remains an explicit activation proof gate.

Before owner activation:
1. Require independent native ARM64 successful reads with production AWS provider,
   plus TLS and chosen memory/deadline evidence; review dependency/license/security.
2. Review live AgentCore native response wrapping and all three SDK-discovered tools;
   host synthetic CallToolResult proof alone is insufficient.
3. Owner provision app-password out of band, then review an exact same-account ARN
   and published **manifest** digest. Never use the test fixture's `aaaa…` digest.
4. Review a real owner-authorized plan; keep existing Outlook/Gmail/CalDAV resources
   unchanged. No real-mail canary or apply is authorized by this draft.
5. Only after the separately reviewed source change and approval, enable runtime;
   verify exact target/catalog/Cedar and then,
   separately, set `HERMES_AGENTCORE_THUNDERMAIL_ENABLED=true` in the intended adapter.
   Shipping this source never changes an active adapter.

Rollback: set the adapter flag false and owner-review runtime disable together with
catalog/policy removal. Keep managed secret metadata disabled separately only when
its removal/recovery is intended. Keep immutable image digest for investigation or
rollback; do not add a shared ECR lifecycle rule that could delete sibling images.
