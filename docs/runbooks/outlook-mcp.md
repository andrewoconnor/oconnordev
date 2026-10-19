# Outlook mail and calendar through AgentCore

## Architecture

`target-outlook.tf` defines an `outlook` OpenAPI target on the Hermes gateway.
The spec in `infra/aws/tools/outlook-openapi.tf` has five GET operations on
Microsoft Graph beta: `listMailFolders`, `listMessages`, `getMessage`,
`listCalendars` and `listEvents`. The beta endpoint accepts OData options
without the `$` prefix, so tool parameters are plain names such as `top` and
`select`. Hermes sees `outlook-<operation>`; the gateway action is
`outlook___<operation>`, with one Cedar permit for each.

The target uses user-delegated OAuth (`AUTHORIZATION_CODE`) with
`Mail.Read`, `Calendars.Read` and `offline_access`. The `hermes-outlook`
credential provider is `CustomOauth2` on the Microsoft `consumers` endpoint. It
authenticates with a `PRIVATE_KEY_JWT` client assertion, signed with PS256 by
the KMS key `alias/hermes-outlook-oauth-signing`. There is no client secret. The
gateway role may use that key only through AgentCore Identity.

## Setup

1. In your Entra directory, register an app for *Personal Microsoft accounts
   only*, with the delegated Microsoft Graph permissions `Mail.Read`,
   `Calendars.Read` and `offline_access`. Its client ID is
   `local.outlook_client_id` in `target-outlook.tf`.
2. Create the certificate with the `outlook_signing_key_arn` stack output and
   tools-account AWS credentials:
   ```sh
   python3 scripts/bootstrap/outlook/build_certificate.py <outlook_signing_key_arn>
   ```
   Upload `outlook-oauth.pem` under *Certificates & secrets → Certificates*. Put
   the printed `x5t#S256` value in `local.outlook_cert_thumbprint`.
3. Apply the `oconnordev-tools` stack.
4. Under *Authentication → Add a platform → Web*, add the stack output
   `outlook_oauth_callback_url` as a redirect URI.
5. Grant consent on the computer where your browser runs, with the adapter's
   `HERMES_AGENTCORE_*` variables and tools-account AWS credentials:
   ```sh
   python3 scripts/bootstrap/oauth/consent.py --tool outlook___listMailFolders
   ```
6. Deploy the adapter.

The certificate is valid for ten years by default. Before it expires, run
`build_certificate.py` again with the same key, upload the new certificate and
update the thumbprint. Run the consent script with `--force` after a scope
change.
