# Gmail through AgentCore

## Architecture

`target-gmail.tf` defines a `gmail` OpenAPI target on the Hermes gateway. The
spec in `infra/aws/tools/gmail-openapi.json` has three GET operations:
`listLabels`, `listMessages` and `getMessage`. Hermes sees them as
`gmail-<operation>`. The gateway action is `gmail___<operation>`, with one Cedar
permit for each.

The target uses user-delegated Google OAuth (`AUTHORIZATION_CODE`) with only the
`gmail.readonly` scope. AgentCore Identity holds the Google refresh token in its
token vault and refreshes it. No Lambda runs for Gmail.

The `hermes-google` credential provider reads the Web OAuth client secret from
`/hermes/google/oauth-client-secret`. The gateway guardrail allows the gateway
role to read only that secret and the other named credentials.

## Setup

1. In Google Auth Platform, use an External audience published to *In
   production*, with the Gmail API enabled. In *Testing*, Google expires the
   refresh token after seven days.
2. Create a **Web application** OAuth client. Its client ID is
   `local.google_oauth_client_id` in `target-gmail.tf`.
3. Before the first apply, store the client secret:
   ```sh
   read -rs CS && aws secretsmanager create-secret --region us-east-1 \
     --name /hermes/google/oauth-client-secret \
     --secret-string "$(jq -cn --arg s "$CS" '{client_secret:$s}')" && unset CS
   ```
4. Apply the `oconnordev-tools` stack.
5. Add the stack output `google_oauth_callback_url` to the Web client's
   *Authorized redirect URIs*.
6. Grant consent once, with the adapter's `HERMES_AGENTCORE_*` variables and
   tools-account AWS credentials:
   ```sh
   python3 scripts/bootstrap/google/consent.py
   ```
   The script calls `gmail___listLabels`. The gateway answers with a `-32042`
   URL elicitation. Approve read-only access in the browser. Google returns to
   AgentCore, and AgentCore redirects to `http://localhost:9090/oauth2/callback`.
   The script then calls `CompleteResourceTokenAuth` with the same Cognito token
   and calls `listLabels` again.
7. Deploy the adapter.

Run the script again if Google revokes the token. Revoke access at
https://myaccount.google.com/permissions.
