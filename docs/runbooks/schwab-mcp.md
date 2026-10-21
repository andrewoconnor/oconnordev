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
returns an authorization link, and the Lambda returns it to Hermes as a tool
error. If Schwab rejects a stored token, the Lambda requests a new link with
`forceAuthentication`. After you sign in to Schwab, AgentCore redirects to the
hosted callback `hermes-oauth-callback` (`oauth-callback.tf`). The callback
calls `CompleteResourceTokenAuth` with the user ID `owner`. It never sees
Schwab tokens. The `hermes-schwab` workload identity allows only this callback
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
5. Ask Hermes for your Schwab accounts. Open the link that Hermes sends, sign in
   to Schwab and approve. Then ask again.

Repeat step 5 when Hermes sends a new link, about once a week.
