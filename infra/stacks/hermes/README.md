# Shared Hermes AgentCore Gateway

The Hermes account stack owns one Cognito-authenticated AgentCore Gateway and one attached Cedar policy engine. GitHub remains a target of that shared Gateway. Future integrations should add their own Gateway target, outbound credential provider/secret and narrowly scoped IAM grant, plus target/tool-specific Cedar policies; they should not create another Gateway or inbound Cognito client.

The shared Gateway role now separates common AgentCore permissions from GitHub-only API-key and secret access. The Gateway remains in `ENFORCE` mode, Cedar validation remains `FAIL_ON_ANY_FINDINGS`, and unmatched requests remain denied. Any Cedar `forbid` continues to override permits.

## GitHub target boundary defaults

The Hermes stack defaults `hermes_github_allowed_repositories` to `["oconnordev"]` and `hermes_github_default_branches` to `{ oconnordev = "master" }`. The Cedar policies for the GitHub target are therefore generated for that repository without any external variable input: reads are limited to the configured owner and that repository set, branch writes are limited to `hermes/*` branches, and draft PRs must target the configured default branch. Setting `hermes_github_allowed_repositories` back to an empty set restores deny-all for the GitHub target.

These are Terraform variable defaults only. If the `oconnordev-hermes` Spacelift stack supplies `TF_VAR_hermes_github_allowed_repositories` or `TF_VAR_hermes_github_default_branches`, the supplied values take precedence and these defaults have no effect. Confirm the stack's environment variables before relying on the defaults.

## GitHub target listing mode

The GitHub target uses `listing_mode = "DEFAULT"`, so AgentCore caches its MCP resource list at the control plane. A `DYNAMIC` target is listed live instead, and policy-engine policy creation cannot do that: it fails with "The gateway has a dynamic target, so its tools must be listed live from the gateway and that listing failed." With `DEFAULT`, tools are synced when the target is created or updated, which is what policy creation and Cedar validation read.

The sync captures whatever the upstream server returns at that moment. GitHub's hosted MCP currently lists 48 tools, so the Gateway advertises more tools than the seven in `adapter/github-mcp-tools.json`. That does not widen authority: Cedar permits only those seven action names, the local adapter narrows `tools/list` to the manifest set, and unmatched calls remain denied.

## Rebuilding the GitHub target's capability catalog

The target's capability catalog can go stale in a way `SynchronizeGatewayTargets` does not repair. Observed: the target routes all seven manifest tools (each verified by calling it) while `tools/list` advertises only four, with all seven Cedar policies `ACTIVE` and structurally identical to one another. The local adapter requires `tools/list` to return exactly the manifest set, so an incomplete catalog blocks the cutover.

`terraform_data.github_target_catalog_rebuild` forces a one-shot replacement of the target, which rebuilds the catalog: `CreateGatewayTarget` performs implicit synchronization against the upstream server. Bump `triggers_replace` when another rebuild is wanted. It is deliberately not a recurring recreation, or every apply would destroy a working target.

The Cedar policies `depends_on` the target, so a replacement re-orders them. If a policy ends up non-`ACTIVE` after the replacement, re-apply — the target's tools are re-synced as part of the same apply.

## AWS target boundary (read-only)

The AWS MCP Server target (`aws`) points at AWS's managed MCP endpoint, `https://aws-mcp.us-east-1.api.aws/mcp`. It is an MCP server target, so the Gateway authenticates with SigV4 via `gateway_iam_role` rather than an API key or an OAuth token. The SigV4 service name is pinned in `hermes_aws_mcp_sigv4_service` so a changed endpoint cannot silently change the signature.

**The Gateway role's IAM policy is the real boundary, not the tool set.** The AWS MCP Server executes AWS API calls with the caller's identity, so this target is read-only only because `ReadOnlyAccess` is attached to the shared Gateway role. `aws___run_script` — the server's API execution tool — inherits exactly those permissions and cannot exceed them. An explicit `Deny` on `secretsmanager:GetSecretValue`, carved out for the GitHub PAT secret that the GitHub target's API-key credential provider still needs, keeps secret values outside the boundary even if the managed policy would otherwise allow them.

`adapter/aws-mcp-tools.json` lists the seven permitted tools and records `aws___get_presigned_url` as deliberately excluded: it mints pre-signed Amazon S3 URLs, and a pre-signed upload URL is a write capability. Cedar policies are generated one-per-tool from that manifest, and the target carries a precondition that the manifest holds exactly seven tools. Each permit pins `principal is AgentCore::OAuthUser` and requires the caller's `scope` claim to carry the gateway's `hermes-mcp/invoke` scope (read from the Cognito resource server, not hardcoded). An unconditional `permit (principal, action == ..., resource == ...)` is rejected by the policy engine's semantic validation with `ALLOW_ALL` — "Policy Engine will allow every request for the specified principal, action and resource combination" — so the condition is required for the policy to be accepted at all, not merely good practice.

Manifest tool names are the AWS MCP Server's own names, which already carry the server's `aws___` namespace. AgentCore prefixes every action with the target name, so the Gateway action is `aws___aws___<tool>` — `aws___aws___run_script`, for example. The doubled prefix is expected. Recording the names without the server's own prefix makes the policy engine reject every policy with "unrecognized action ... did you mean `aws___aws___run_script`". These same names are what Hermes sees as its tool names, since the adapter strips only the target's prefix.

Only the Hermes account (`421680664125`) is in scope. Org-wide access is **not** achievable through a Gateway target: multi-account switching is implemented by the MCP Proxy for AWS using profiles from local `~/.aws/config`, and a Gateway target signs every request with its single role. `aws___run_script` cannot bridge the gap either — it inherits the role's IAM permissions but runs without network access, so it cannot call `sts:AssumeRole`.

## Naming/state migration

The old GitHub-specific Terraform addresses are migrated with `moved` blocks. Physical names change for the AgentCore Gateway (`hermes-github` → `hermes`), policy engine (`hermes_github_policy_engine` → `hermes_policy_engine`), Gateway role (`hermes-github-agentcore-gateway` → `hermes-agentcore-gateway`), and alarm (`hermes-github-gateway-user-errors` → `hermes-gateway-user-errors`). These require replacements: expect a new Gateway ID/URL and policy-engine ID, recreation/rebinding of its target and Cedar policies, and recreation of the role and its inline policies. This is intentionally a coordinated cutover before adding more targets; review the actual state-backed plan before applying. The previously noted console-created `test` policy must be identified and reconciled/imported or deliberately handled before deleting/replacing the existing policy engine; its ID is not guessed here.

Cognito's shared pool, resource-server, and app-client display names now use `hermes-mcp`. With AWS provider 6.66.0, changing the user-pool and app-client names is in-place, so the pool ID/issuer and client ID/secret should remain stable. The resource-server `identifier` and Cognito domain prefix are replacement-only: the scope changes from `hermes-github/invoke` to `hermes-mcp/invoke`, and the token URL prefix changes from `hermes-github-<account>` to `hermes-mcp-<account>`. The resource server uses create-before-destroy so both scopes can exist while the client and Gateway move to the new scope; the old Cognito domain prefix must be replaced, so token issuance may briefly be interrupted. Any consumers must switch to the new token URL and scope after applying. The `hermes_github_*` Terraform outputs remain compatibility aliases by output name, but their values follow the new generic configuration. Inspect the state-backed plan before applying; no client configuration or credentials are changed by this PR.

## Custom endpoint and account boundary

AgentCore Gateway does not have a native custom-domain Terraform resource; AWS documents CloudFront as the reverse proxy. The current repository places `oconnor.dev`, its ACM certificate, and its Route53 zone in the production stack/account, while AgentCore is in the Hermes stack/account. Accordingly, CloudFront and DNS are managed in the production stack and the origin hostname is passed from Hermes through a non-secret Spacelift stack-dependency output reference.

The existing production certificate covers `oconnor.dev` and `*.oconnor.dev`; it does **not** cover `mcp.hermes.oconnor.dev`. The endpoint selected here is `https://mcp.oconnor.dev/mcp`, which is covered by the existing wildcard. To use `mcp.hermes.oconnor.dev`, first add that exact name or `*.hermes.oconnor.dev` to the ACM certificate and complete DNS validation.

The CloudFront distribution applies a US-only geo whitelist for the single client VM, forwards MCP methods and viewer headers except `Host`, disables caching, uses the managed security-headers response policy, and uses HTTPS to the Gateway origin. The default root object maps `/` to `/mcp` as a convenience. The endpoint does not bypass Cognito or Cedar authorization. The distribution is conditionally absent while the Spacelift-provided Gateway hostname input is empty, so the production stack can still validate before its upstream output exists. Checkov exceptions are documented inline for the single-origin/no-failover design, no WAF fixed cost, and intentionally disabled access logs.

## Deployment sequence (not performed by this PR)

1. Inspect the current Hermes state and remote policy-engine contents. Reconcile the console-created `test` policy first; review a state-backed plan and confirm all address moves and expected replacements, then apply the Hermes stack to publish the new Gateway hostname.
2. Apply the Spacelift management stack so the Hermes output is wired to the production stack input.
3. Review and apply the production stack to create the CloudFront distribution and `A`/`AAAA` alias records. Wait for CloudFront deployment and DNS propagation before switching clients.
4. Test Cognito authentication, MCP initialize/tools/list/call through `https://mcp.oconnor.dev/mcp`, CloudFront forwarding of `Authorization` and MCP headers, and Cedar allow/deny behavior. Do not remove the existing direct GitHub path until those tests pass.

This PR adds one new MCP target (`aws`) and generalizes the local adapter so each target supplies its own tool manifest, tool prefix and target request headers; the GitHub adapter's behaviour and its seven-tool allowlist are unchanged. No plan, apply, DNS change, deployment, or client cutover has been performed.
