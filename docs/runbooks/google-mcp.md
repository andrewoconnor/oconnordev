# Gmail and Google Calendar through AgentCore

## Architecture

`target-google.tf` defines a `google` OpenAPI target on the Hermes gateway. The
spec in `infra/aws/tools/google-openapi.tf` has five GET operations on
`https://www.googleapis.com`: Gmail `listLabels`, `listMessages` and
`getMessage`, and Calendar `listCalendars` and `listEvents`. Hermes sees them as
`google-<operation>`. The gateway action is `google___<operation>`, with one
Cedar permit for each.

The target uses user-delegated Google OAuth (`AUTHORIZATION_CODE`) with only the
`gmail.readonly` and `calendar.readonly` scopes. AgentCore Identity holds the
Google refresh token in its token vault and refreshes it. No Lambda runs for
Google.

The `hermes-google` credential provider reads the Web OAuth client secret from
`/hermes/google/oauth-client-secret`. The gateway guardrail allows the gateway
role to read only that secret and the other named credentials.

## Setup

1. In Google Auth Platform, use an External audience published to *In
   production*, with the Gmail and Google Calendar APIs enabled. In *Testing*,
   Google expires the refresh token after seven days.
2. Create a **Web application** OAuth client. Its client ID is
   `local.google_oauth_client_id` in `target-google.tf`.
3. Before the first apply, store the client secret as
   `{"client_secret": "..."}` in `/hermes/google/oauth-client-secret`.
4. Apply the `oconnordev-tools` stack.
5. Add the stack output `google_oauth_callback_url` to the Web client's
   *Authorized redirect URIs*.
6. Grant consent on the computer where your browser runs, with the adapter's
   `HERMES_AGENTCORE_*` variables and tools-account AWS credentials:
   ```sh
   python3 scripts/bootstrap/google/consent.py
   ```
   The script calls `google___listLabels`. The gateway answers with a `-32042`
   URL elicitation. Approve read-only access in the browser. Google returns to
   AgentCore, and AgentCore redirects to `http://localhost:9090/oauth2/callback`.
   The script then calls `CompleteResourceTokenAuth` with the same Cognito token
   and calls `listLabels` again.
7. Deploy the adapter.

Run the script with `--force` after a scope change or if Google revokes the
token. Revoke access at https://myaccount.google.com/permissions.
