# Thundermail native Rust MCP

## Architecture

The runtime reads only `oconnor@thundermail.com` at certificate-verified
`mail.thundermail.com`: IMAP on port 993 and the default CalDAV calendar
`/dav/cal/oconnor%40thundermail.com/default/` on port 443. Both use the same app
password. Source: `infra/aws/tools/lambdas/thundermail_mcp/`.

The gateway invokes the Lambda directly as a native Lambda target
(`target_configuration.mcp.lambda`). There is no Function URL, HTTP server or
Lambda Web Adapter. AgentCore sends the arguments as the event and the tool name in
`context.client_context.custom.bedrockAgentCoreToolName`. See the
[AWS native Lambda target contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html).

The tools are `imap_list_mailboxes`, `imap_search_messages`, `imap_get_message`
and `caldav_list_events`.
Hermes sees them as `thundermail-<name>`. The gateway action is
`thundermail___<name>`. The runtime refuses unknown tools, account or host
overrides, and write actions.

The gateway `SchemaDefinition` supports only types, properties, required fields
and descriptions. The runtime enforces the full schema. The adapter exposes the
strict schemas from `agents/hermes/adapter/thundermail-mcp-tools.json`. A test
requires them to equal `tool-schemas.json`.

## Secret and permissions

Terraform manages the secret metadata at `/hermes/thundermail/app-password`, not
the value. Store only the dedicated app password as the plaintext `SecretString`:
1–4096 bytes with no control characters. The runtime uses it unchanged; do not
add JSON, quotes or a trailing newline. Never put the value into Terraform, a
build, a workflow or a chat.

The runtime role can only read that secret and write its own logs. The gateway
can only invoke the function. The 128 MiB arm64 Lambda has reserved concurrency 1
and 14-day logs.

## Build and test

The Dockerfile builds and runs on the same pinned `provided.al2023` image. mise
installs the Rust version from `mise.toml`. Cargo uses `--locked`. The release
binary is `/var/runtime/bootstrap`.

```sh
mise install rust
mise run test:thundermail-rust
mise run test:thundermail-sdk
```

The image workflow runs `native_smoke.py` against the built image. The smoke test
sends invalid calls through a synthetic Runtime API. It does not read mail.

## Deploy a new image

Copy the digest from the publish job summary into `local.thundermail_image_digest`.
Merge the change and apply the `oconnordev-tools` stack. To roll back, revert the
change. Do not add an ECR lifecycle rule; other images share the repository.
