# Shared Hermes AgentCore Gateway

The Hermes account stack owns one Cognito-authenticated AgentCore Gateway and one attached Cedar policy engine. GitHub remains a target of that shared Gateway. Future integrations should add their own Gateway target, outbound credential provider/secret and narrowly scoped IAM grant, plus target/tool-specific Cedar policies; they should not create another Gateway or inbound Cognito client.

The shared Gateway role now separates common AgentCore permissions from GitHub-only API-key and secret access. The Gateway remains in `ENFORCE` mode, Cedar validation remains `FAIL_ON_ANY_FINDINGS`, and unmatched requests remain denied. Any Cedar `forbid` continues to override permits.

## GitHub target boundary defaults

The Hermes stack defaults `hermes_github_allowed_repositories` to `["oconnordev"]` and `hermes_github_default_branches` to `{ oconnordev = "master" }`. The Cedar policies for the GitHub target are therefore generated for that repository without any external variable input: reads are limited to the configured owner and that repository set, branch writes are limited to `hermes/*` branches, and draft PRs must target the configured default branch. Setting `hermes_github_allowed_repositories` back to an empty set restores deny-all for the GitHub target.

These are Terraform variable defaults only. If the `oconnordev-hermes` Spacelift stack supplies `TF_VAR_hermes_github_allowed_repositories` or `TF_VAR_hermes_github_default_branches`, the supplied values take precedence and these defaults have no effect. Confirm the stack's environment variables before relying on the defaults.

## GitHub target listing mode

The GitHub target uses `listing_mode = "DEFAULT"`, so AgentCore caches its MCP resource list at the control plane. A `DYNAMIC` target is listed live instead, and policy-engine policy creation cannot do that: it fails with "The gateway has a dynamic target, so its tools must be listed live from the gateway and that listing failed." With `DEFAULT`, tools are synced when the target is created or updated, which is what policy creation and Cedar validation read.

The sync captures whatever the upstream server returns at that moment. GitHub's hosted MCP currently lists 43 tools, so the Gateway advertises more tools than the seven in `adapter/github-mcp-tools.json`. That does not widen authority: Cedar permits only those seven action names, the local adapter narrows `tools/list` to the manifest set, and unmatched calls remain denied.

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

This PR adds no new MCP target and does not generalize the local GitHub-only adapter/tool allowlist. Future integrations can be attached to the shared Gateway, but Hermes-side exposure of their tools requires a separate adapter/manifest change. No plan, apply, DNS change, deployment, or client cutover has been performed.
