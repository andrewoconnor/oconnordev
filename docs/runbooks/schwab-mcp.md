# Schwab accounts and market data through AgentCore

## Architecture

`target-schwab.tf` defines a `schwab` Lambda target on the Hermes gateway. The
gateway invokes `hermes-schwab` (`schwab-runtime.tf`) with its IAM role. The
tools are in `infra/aws/tools/lambdas/schwab/tools.json`: `getAccountNumbers`,
`listAccounts`, `getAccount`, `getQuotes`, `getPriceHistory`, `getMarketHours`
and `searchInstruments`. Each tool is one GET on an account or market data path
of `https://api.schwabapi.com`. There are no order endpoints. Hermes sees
`schwab-<tool>`; the gateway action is `schwab___<tool>`, with one Cedar permit
for each.

The Lambda gets the Schwab token from AgentCore Identity. It calls
`GetWorkloadAccessTokenForUserId` on its own workload identity `hermes-schwab`
with the user ID `owner`. Then it calls `GetResourceOauth2Token` on the
`hermes-schwab` credential provider with the `api` scope. Schwab defines no
other scope. The provider is `CustomOauth2` with Schwab's authorize and token
endpoints and HTTP Basic client authentication. It reads the app secret from
`/hermes/schwab/oauth-client-secret`. AgentCore Identity stores the refresh
token and refreshes the 30-minute access token. The Lambda sends only the
bearer token and `Accept: application/json`, because Schwab rejects GETs that
have `Content-Type: application/json`.

Schwab refresh tokens expire seven days after consent. Then AgentCore Identity
returns an authorization URL and a session URI. If Schwab rejects a stored
token, the Lambda requests them again with `forceAuthentication`. The Lambda
signs the session URI with the KMS HMAC key in `oauth-callback.tf` and returns a
link to `/start` on the hosted callback `hermes-oauth-callback` to Hermes as a
tool error.

1. `/start` verifies the signature, sets a 10-minute `__Host-consent` cookie
   with it, and redirects to the AgentCore authorization URL.
2. After you sign in to Schwab, AgentCore redirects to `/callback`. The callback
   verifies the cookie against the session URI, so it accepts only the browser
   that opened the link.
3. The callback shows a password form. It checks the password of the Cognito
   user `owner` in the `hermes-mcp-m2m` user pool with `AdminInitiateAuth`
   through its own app client `hermes-oauth-callback`.
4. Only after both checks does it call `CompleteResourceTokenAuth` with the
   user ID `owner`.

A request without a valid cookie never reaches Cognito. AgentCore exchanges
the code with the callback's credentials, so the callback role can read the app
secret. The callback never sees Schwab tokens. The `hermes-schwab` workload identity allows only this callback
as a return URL. A link is valid for 10 minutes.

## Setup

1. Before the first apply, create the secret with a placeholder:
   `{"client_secret": "pending"}` in `/hermes/schwab/oauth-client-secret`.
2. Apply the `oconnordev-tools` stack.
3. At developer.schwab.com, create an app for **Accounts and Trading Production**
   and **Market Data Production**. Use the stack output
   `schwab_oauth_callback_url` as its exact callback URL.
4. When the app is *Ready For Use*, put its App Key in `local.schwab_app_key` in
   `target-schwab.tf`, store its Secret as `{"client_secret": "..."}` in the
   secret, and apply again.
5. With credentials for the TOOLS account, set the password of the Cognito user
   `owner`. Generate it in your password manager. The pool requires at least 20
   characters, with uppercase, lowercase, a number and a symbol:
   ```sh
   POOL=$(aws cognito-idp list-user-pools --max-results 60 \
     --query "UserPools[?Name=='hermes-mcp-m2m'].Id" --output text)
   read -rs PASSWORD
   aws cognito-idp admin-set-user-password --user-pool-id "$POOL" \
     --username owner --password "$PASSWORD" --permanent
   unset PASSWORD
   ```
6. Ask Hermes for your Schwab accounts. Open the link that Hermes sends, sign in
   to Schwab and approve. On the callback page, enter the `owner` password. Use
   the same browser for the whole flow. Then ask again.

Repeat step 6 when Hermes sends a new link, about once a week.
