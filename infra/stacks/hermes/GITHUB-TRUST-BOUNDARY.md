# Hermes GitHub trust boundary — architecture and deployment runbook

## Status and scope

This change is Terraform/code/documentation only. It has not been applied, deployed, connected to live GitHub, or added to the active Hermes configuration. Tests use synthetic repositories and mocked HTTP. The GitHub private key value is never read during this work.

The existing `infra/stacks/hermes` root is preserved. It assumes the existing Spacelift role in account `421680664125`, external ID `spacelift-general`, and region `us-east-1`. The existing Spacelift role remains the deployment identity; the runtime roles below are separate. No changes are made to Spacelift authentication, GitHub App settings, branch protections, production account DNS/ACM, or existing direct GitHub credentials.

## Architecture

```text
Hermes 0.21.5
  └─ local stdio adapter (no AWS credentials)
       ├─ OAuth client_credentials → dedicated Cognito app client
       └─ fixed HTTPS POST + Bearer access token → AgentCore Gateway /mcp
            └─ custom JWT checks: Cognito issuer, client_id, scope, token_use=access, exp/signature
                 └─ Gateway IAM role: lambda:InvokeFunction on one Lambda ARN
                      └─ GitHub connector Lambda
                           ├─ Secrets Manager GetSecretValue at runtime for the exact existing secret ARN
                           └─ short-lived installation token scoped to one allowlisted repository
```

The Gateway target name is `github`; AgentCore prefixes its target tools as `github___<logical_tool>`. The local adapter strips that prefix and exposes exactly these five logical tools to Hermes: `repository_info`, `read_files`, `submit_change`, `revise_change`, and `change_status`.

### Provider support

The Hermes root pins `hashicorp/aws ~> 6.66.0`. Provider source tagged `v6.66.0` includes `aws_bedrockagentcore_gateway` (including required `authorizer_type`, role ARN, and custom JWT authorizer fields) and `aws_bedrockagentcore_gateway_target` with a native Lambda/MCP target and inline tool schemas. The root adds `hashicorp/archive ~> 2.7.0` only to package the local Lambda source. No API Gateway, ECS service, custom DNS, ACM certificate, AWS Cloud Control provider, or external MCP server is proposed.

The gateway authorizer uses the Cognito OIDC discovery URL, `allowed_clients` set to the dedicated client ID, the one custom OAuth scope, and a custom claim requiring `token_use == "access"`. Cognito access tokens identify the app client with `client_id`; this configuration does not rely on an `aud` claim. AgentCore validates token signature, issuer, and expiration as part of JWT verification. The exact provider source-level schema is present in AWS provider v6.66.0; Terraform format/validate/plan still need to run before merge.

References:
- [AWS provider 6.66.0 AgentCore Gateway target](https://registry.terraform.io/providers/hashicorp/aws/6.66.0/docs/resources/bedrockagentcore_gateway_target)
- [AWS provider source at v6.66.0 — Gateway resource](https://github.com/hashicorp/terraform-provider-aws/blob/v6.66.0/internal/service/bedrockagentcore/gateway.go)
- [AWS AgentCore Lambda target event contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
- [AWS AgentCore inbound JWT authorizer](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
- [AWS AgentCore Gateway metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-gateway-metrics.html)
- [Hermes MCP configuration reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference)

## Existing repository resources reviewed

- `infra/stacks/general`: Identity Center and the central Spacelift IAM role; no existing AgentCore Gateway, Cognito, Lambda connector, Secrets Manager secret/version, CloudWatch log/alarms for this integration, GitHub connector, or DNS/custom-domain resources.
- `infra/stacks/spacelift`: existing Spacelift Terraform root and stack definitions; this change does not alter Spacelift authentication or its current deployment identity.
- `infra/stacks/hermes`: existing Hermes account root, AWS provider assume-role configuration, and account-local `spacelift` IAM role. No existing AgentCore, Cognito, connector Lambda, or related operational resources were found.
- Existing AWS provider constraint: `~> 6.66.0`; the patch retains it. No Route 53 or ACM edits are included.

## Proposed Terraform resources

- Cognito: one user pool, one custom resource server/scope (`hermes-github/invoke`), one Cognito domain, and one dedicated M2M app client using `client_credentials`.
- AgentCore: one `CUSTOM_JWT` MCP Gateway and one native Lambda target containing exactly five inline tool definitions.
- IAM: one Lambda execution role/policy, one distinct AgentCore service integration role/policy, and the existing Spacelift deployment identity left separate and unchanged.
- Lambda: one Node.js 24.x connector function, reserved concurrency 5, 256 MiB memory, 30-second timeout, and a 30-day CloudWatch log group.
- CloudWatch: Lambda error/throttle alarms, a sanitized GitHub-auth-failure metric filter/alarm, and an AgentCore `UserErrors` alarm for repeated 4xx responses including unauthorized requests. Alarm actions are not configured because no notification destination was specified.
- Packaging: one `archive_file` data source. No resource reads or writes the secret value during Terraform evaluation.

## Trust and authorization controls

### Repository boundary

- The owner is hard-coded to `andrewoconnor`; tools accept repository name only, not an owner, URL, REST path, or GraphQL query.
- `hermes_github_allowed_repositories` is a trusted Terraform variable embedded into Lambda environment configuration. Its default is an empty set, which denies all repository access until explicitly configured in the Hermes Spacelift stack.
- Before a tool operation, the connector checks the repository against that allowlist and verifies GitHub metadata reports the exact personal owner (`owner.type == User`, login `andrewoconnor`, expected full name). Organization repositories and other owners fail closed.
- Each installation token request is restricted server-side to the one repository being accessed and the minimum requested permissions. Tokens are held only in invocation memory, are never cached/persisted, and are never included in results or logs.
- Writes use only `hermes/<request-id>` feature branches and draft pull requests targeting the repository's configured default branch. No direct default-branch push, merge, approval, workflow dispatch, secrets/environment/deployment operation, or repository administration API exists in the code.
- New submissions require the default branch head SHA. Revisions require the current PR head SHA, verify an open draft authored by this App, and reject stale/foreign branches. Request IDs make retries safe; branch/PR lookups recover after response loss.
- Inputs are allow-listed by exact tool and field names. The connector limits writes/reads to 25 files, 128 KiB per file, and 512 KiB total; rejects binary/NUL content, traversal, unsupported paths/types, duplicate paths, unknown arguments, unknown tools, and oversized values. Submitted content is never executed by this connector.

### GitHub App permissions expected

- Contents: Read and write
- Pull requests: Read and write
- Commit statuses: Read-only
- Metadata: Read-only
- Everything else: No access

No additional GitHub App permission is proposed. Installation tokens request only `contents: write`, `pull_requests: write`, and `statuses: read` for the single current repository; GitHub's required metadata read is implicit. The App may be installed on more personal repositories; the AWS-side allowlist remains the enforcement boundary.

A same-repository draft PR can trigger repository CI workflows. Before enabling this path, review repository workflow behavior so untrusted proposal code cannot exfiltrate Actions secrets or receive elevated write credentials. This connector cannot read GitHub Actions secrets, but workflow execution policy is a separate repository control.

## Secret and Cognito state handling

The existing secret `/hermes/github/app-private-key` is treated as external and is referenced only through `data.aws_secretsmanager_secret` metadata. The Lambda environment contains the secret ARN, not its value. The Lambda role has `secretsmanager:GetSecretValue` for that exact ARN and only `logs:CreateLogStream`/`logs:PutLogEvents` for its own pre-created log group. It has no IAM, Lambda deployment, Secrets Manager write, Organizations, Terraform-state, or Spacelift permissions.

The secret must be populated externally with the PEM as a SecretString. If it is encrypted with a customer-managed KMS key, the role as written will not have `kms:Decrypt`; do not broaden the policy implicitly. For this initial boundary, use the Secrets Manager AWS-managed encryption key or stop and review a narrowly scoped KMS design first.

**The Cognito app client secret is generated by AWS and will be present in Terraform/Spacelift state** because the provider manages `aws_cognito_user_pool_client`. The attribute is provider-sensitive, no output exposes it, and it is not placed in Lambda environment variables or the repository. Restrict and encrypt Spacelift state access as a deployment secret. A human with authorized Hermes-account Cognito administration can retrieve the app client credential through an approved secured path and place it in the local adapter's protected environment/secret store. Hermes receives only this dedicated Cognito client credential; it receives no AWS credentials, GitHub private key, or GitHub installation token. Rotating/replacing the Cognito client secret may require state-safe rotation planning.

## Local forwarding adapter

`adapter/hermes_github_adapter.py` is a dependency-free stdio MCP bridge. It reads the dedicated Cognito client ID/secret and one Gateway URL from process environment, obtains a client-credentials token requesting only `hermes-github/invoke`, caches it in memory, refreshes 60 seconds before expiry, and retries one Gateway `401` exactly once. It validates the token response type/scope, uses fixed HTTPS endpoint patterns and `/mcp` path, disables redirects, uses finite connect/read timeouts, limits request/response sizes, and never logs credentials, bearer tokens, authorization headers, or MCP payloads. MCP tool calls cannot alter the destination or invoke arbitrary HTTP methods/URLs.

A config example for a future, manually reviewed Hermes profile can use a stdio MCP server entry with `command` pointing at the installed adapter, and environment references to protected local variables. Keep the endpoint and client credential out of checked-in `config.yaml`, CLI arguments, and shell history. This PR deliberately does not edit live Hermes configuration. Verify the environment interpolation behavior of the deployed Hermes 0.21.5 build before using a profile config; alternatively launch the adapter from a user-managed secure wrapper that supplies its environment.

## Bootstrap and migration sequence

1. Review this branch and draft PR; run local tests and CI. Do not merge/apply from this PR description.
2. In the existing Hermes Spacelift stack, configure `hermes_github_app_id` and `hermes_github_installation_id` (non-secret Terraform variables) and set `hermes_github_allowed_repositories` to the initial approved personal repository names. The ID variables now default to empty so a bootstrap plan can run; the connector rejects every operation with `github_app_not_configured` until both IDs are set. The allowlist also defaults to empty/deny-all.
3. Manually ensure the already-created Secrets Manager secret `/hermes/github/app-private-key` contains the correct PEM as a SecretString. Do not put that value in Terraform, code, or chat. Confirm its encryption key meets the IAM constraint above.
4. Apply the reviewed Terraform through the existing Spacelift workflow only. This creates the Cognito M2M client secret in Terraform state. Protect Spacelift state and restrict who can view it.
5. Read the non-secret outputs `hermes_github_gateway_url`, `hermes_github_cognito_token_url`, `hermes_github_cognito_client_id`, and `hermes_github_cognito_scope`. Securely provision the generated Cognito client secret into the local adapter environment. Do not copy it into this repository or Hermes YAML.
6. Install/test the adapter locally using the mocked unit tests. Configure it in a disposable Hermes profile only after manually reviewing the fixed endpoints and local secret handling.
7. Make safe read-only calls (`repository_info`, `read_files`) on an allowlisted test repository. Then create/revise a harmless draft PR branch and verify the PR is draft, targets the configured default branch, and that the branch head/base SHA conflict checks work.
8. Check Lambda/Gateway metrics and alarms; ensure no request-body logging destination was enabled. Review the App's repository installation and confirm only required App permissions are granted.
9. Only after the new path is proven end-to-end, disable the old direct GitHub MCP/PAT path from Hermes and revoke/remove any old credential that bypasses this boundary. Do not remove old access before successful validation.

No custom hostname is needed for v1. If a hostname becomes necessary later, delegate `hermes.oconnor.dev` to the Hermes account and issue ACM certificates in that account; do not move Production's Route 53/ACM ownership into this stack.

## Validation and limitations to report

- Local test commands: from `infra/stacks/hermes/lambda`, `node --test`; from `infra/stacks/hermes`, `PYTHONPATH=adapter python3 -m unittest discover -s adapter/test -v`.
- Terraform commands: from `infra/stacks/hermes`, run `terraform fmt -check -recursive` (or `terraform fmt -recursive` before commit), `terraform init -backend=false`, and `terraform validate` when the CLI/provider download is available. Spacelift plan is the eventual integration validation; do not apply from this task.
- AgentCore Gateway and its native Lambda target are representable with the repository's AWS provider `~> 6.66.0`; the provider v6.66.0 gateway page is not fully populated in Registry docs, so the exact source schema and target docs are used. A real plan is still required to confirm the pinned provider binary accepts every block.
- No end-to-end AWS, Cognito token, AgentCore invocation, GitHub API, App installation, or Secrets Manager secret-value test has been performed. The local suite uses synthetic data and mocked transport only.
- Gateway vended request/response logs can contain raw MCP payloads. This configuration intentionally does not enable Gateway request-body log delivery; it uses service metrics for `UserErrors` and emits sanitized Lambda logs only. Enabling vended Gateway logs later requires a separate privacy review and a redaction strategy.
- The generated Cognito client secret is in Terraform state, as documented above. No credential value is output or committed.
- The Gateway `UserErrors` alarm counts all 4xx responses (not only authorization failures); AgentCore does not expose a distinct JWT-failure CloudWatch metric in the current design.
