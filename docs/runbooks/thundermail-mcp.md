# Thundermail native Rust MCP

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

## Secret, runtime and cost

Terraform manages the secret metadata at `/hermes/thundermail/app-password`
with 30-day recovery. Terraform never manages the secret value. The owner stores a
dedicated app password as `{"version": 1, "password": "..."}` with no other keys.
Do not copy a local Himalaya credential. Never pass the value into Terraform, a
build, a workflow or a chat.

`local.thundermail_image_digest` in `thundermail-runtime.tf` pins the deployed
ECR manifest digest. The runtime gets only `GetSecretValue` on the secret. The
gateway gets only `InvokeFunction` on the function ARN. The OAuth principal, scope
and ENFORCE engine do not change.

Use the shared `oconnordev-tools` ECR repository and existing ECR-only publisher.
Its role permissions do not gain Lambda updates, PassRole, secrets or apply rights.
Tag prefixes are collision conventions, not ECR IAM isolation. The existing
Microsoft pull grant is byte-equivalent while disabled; enabled it adds only the
exact Thundermail function ARN. No new repository, gateway, VPC, NAT or customer
KMS key. A serialized 128 MiB ARM64 Lambda scales to zero with finite 14-day logs.
Secret metadata, ECR storage/scanning, requests, execution, logs and the existing
gateway can incur charges.
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

## Publication

A master run publishes the saved tested image to ECR after the ARM64 check job
passes. Before OIDC, the publisher verifies the archive hash and image ID and
confirms that fresh master has the same image inputs. It never rebuilds. After the
push, it reads back the ECR digest and compares it to the push output. Publication
does not update Lambda or apply IaC.

Offline tests plan the configuration with mocked providers.
Schema-free Cedar evaluation checks scoped policy decisions only.

## Deploy a new image

Copy the digest from the publish job summary into `local.thundermail_image_digest`.
Merge the change; the `oconnordev-tools` Spacelift stack deploys it. To roll back,
revert the change. Do not add a shared ECR lifecycle rule that could delete sibling
images.
