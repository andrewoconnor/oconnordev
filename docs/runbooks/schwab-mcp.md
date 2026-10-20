# Schwab accounts and market data through AgentCore

## Architecture

`target-schwab.tf` defines a `schwab` OpenAPI target on the Hermes gateway. The
spec in `infra/aws/tools/schwab-openapi.tf` has seven GET operations on
`https://api.schwabapi.com`: `getAccountNumbers`, `listAccounts`, `getAccount`,
`getQuotes`, `getPriceHistory`, `getMarketHours` and `searchInstruments`. It has
no order endpoints. Hermes sees `schwab-<operation>`; the gateway action is
`schwab___<operation>`, with one Cedar permit for each.

The target uses user-delegated OAuth (`AUTHORIZATION_CODE`) with the `api`
scope. Schwab defines no other scope and rejects unknown ones. The `hermes-schwab` credential provider is
`CustomOauth2` with Schwab's authorize and token endpoints and HTTP Basic client
authentication. It reads the app secret from `/hermes/schwab/oauth-client-secret`.

Schwab refresh tokens expire seven days after consent. The gateway then answers
with a `-32042` consent link. The adapter returns the link to Hermes as a tool
result, and Hermes shows it to you. After you sign in to Schwab, AgentCore
redirects to the hosted callback in `oauth-callback.tf`. That Lambda mints a
Cognito token for the adapter client and calls `CompleteResourceTokenAuth`, so
no local script is needed. It never sees Schwab tokens. AgentCore only redirects to return URLs that
are registered on the gateway's workload identity; `gateway-workload-identity.tf`
registers the hosted callback and `http://localhost:9090/oauth2/callback`.

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
5. Deploy the adapter, then ask Hermes for your Schwab accounts. Open the link it
   shows, sign in to Schwab and approve. Then ask again.

Repeat step 5 when Hermes shows a new link, about once a week.
