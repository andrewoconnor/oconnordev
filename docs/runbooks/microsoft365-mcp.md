# Microsoft365 personal-mail MCP

## Architecture

Source and Docker build context: `infra/aws/tools/lambdas/microsoft365_mcp/`.
The wrapper uses pinned `@softeria/ms-365-mcp-server@0.166.0`. See the
[runtime contract](../../infra/aws/tools/lambdas/microsoft365_mcp/INTEGRATION.md)
for package and base-image pins, deadlines and argument schemas.

Path: Cognito JWT `hermes-mcp/invoke` → shared ENFORCE Cedar engine →
`microsoft365` MCP-server target → gateway SigV4 → AWS_IAM Function URL `/mcp` →
arm64 Lambda with Lambda Web Adapter → Microsoft Graph.

`microsoft365-runtime.tf` pins the image digest, the client ID and the owner
`homeAccountId` in locals. Keep the `homeAccountId` byte-for-byte, including the
zero-prefixed UID. The `oconnordev-tools` Spacelift stack has `autodeploy=false`.

## Catalog and authorization

The adapter exposes five tools, routed as `microsoft365___<name>`:

* `list-mail-messages`
* `get-mail-message` (`messageId`)
* `list-mail-folders`
* `list-mail-child-folders` (`mailFolderId`)
* `list-mail-folder-messages` (`mailFolderId`)

Cedar permits these actions for the existing OAuth scope. The runtime enforces
the owner identity, strict arguments and size limits. No write, attachment,
calendar, user or generic Graph tool is exposed.

## Cache and permissions

The MSAL cache is in `/hermes/microsoft365/msal-cache`. Only the runtime role can
read and write it. Reserved concurrency 1 and a mutex serialize cache refresh.
Stop all other writers, including the bootstrap helper, while the runtime is
deployed. A missing, corrupt or wrong-owner cache fails closed.

The gateway can invoke the Function URL. It cannot read the cache. Secret values
never go into IaC, state, CI or chat. Gateway logging follows
[gateway-log-privacy.md](gateway-log-privacy.md).

## Bootstrap an empty cache

Use bootstrap only when the secret has no versions and the Lambda does not exist.
Get owner approval first, because the helper starts OAuth consent and writes the
cache. Run it in AWS CloudShell in TOOLS `421680664125`, `us-east-1`, from a clean
master checkout. Never paste device codes, passwords or MFA responses into chat.

The client uses `https://login.microsoftonline.com/consumers` with delegated
`Mail.Read`, `User.Read`, `openid`, `profile` and `offline_access` only. Stop if
the consent screen asks for a different client, scope or account.

```sh
npm ci --prefix infra/aws/tools/lambdas/microsoft365_mcp --ignore-scripts --no-audit --no-fund
npm ci --prefix scripts/bootstrap/microsoft365 --ignore-scripts --no-audit --no-fund
npm test --prefix scripts/bootstrap/microsoft365
node scripts/bootstrap/microsoft365/cli.mjs
```

The caller needs STS `GetCallerIdentity`, `lambda:GetFunction` on
`hermes-microsoft365-mcp`, and `secretsmanager:DescribeSecret`, `PutSecretValue`
and `GetSecretValue` on
`arn:aws:secretsmanager:us-east-1:421680664125:secret:/hermes/microsoft365/msal-cache-CnJLNM`.

1. The helper shows the caller ARN, region, client, scopes and secret. It stops
   if the secret has a version or the Lambda exists.
2. Type `YES` to approve consent and the one secret write.
3. Enter the displayed code at https://microsoft.com/devicelogin with the intended
   personal account.
4. The helper shows the username and `homeAccountId`. Type `YES` if they are correct.
5. The helper writes the cache once and reads it back. It prints the
   `homeAccountId` and client ID. Put them in the locals if they changed.

If a write or readback fails, do not run the helper again. A version can already
exist. Revoke consent at Microsoft separately if you cancel after consent.

## Deploy a new image

Copy the digest from the publish job summary into `local.microsoft365_image_digest`.
Merge the change and apply the `oconnordev-tools` stack. To roll back, revert the
change. Do not add an ECR lifecycle rule; other images share the repository.

## Offline verification

```sh
mise run test:microsoft365-bootstrap
mise run test:python
mise run test:opentofu-boundary
```
