# Plaid existing Items through AgentCore

`plaid` is a native AgentCore Lambda target. The ARM Python ZIP runtime reads
`/hermes/plaid/credentials` from Secrets Manager on each call. IaC creates only
that container, not its value. Reads are deliberately uncached, including
`listItems`, so owner credential/configuration updates take effect on the next
invocation. `listItems` avoids Plaid calls, not the Secrets Manager read.
The dedicated role can read that exact secret and
write its own fourteen-day Lambda logs. The Gateway receives only exact-function
invoke permission, not Plaid secret access. There is no Function URL, AgentCore
Identity/OAuth provider, database, container, VPC or NAT for Plaid.

## Tool contract

Hermes names use `plaid-`; Gateway actions use `plaid___`.

| Tool | Arguments | Read operation |
| --- | --- | --- |
| `listItems` | none | Local configured aliases, institution names and products |
| `getAccounts` | `item` | `/accounts/get` |
| `getTransactions` | `item`, `startDate`, `endDate`, optional `count`, `offset` | `/transactions/get` |
| `getItemStatus` | `item` | `/item/get` |
| `getRecurringTransactions` | `item` | `/transactions/recurring/get` |
| `getLiabilities` | `item` | `/liabilities/get` |
| `getHoldings` | `item` | `/investments/holdings/get` |

All provider operations are read-only POSTs to exactly
`https://production.plaid.com`. Credentials occur only in server-side JSON POST
bodies. Redirects are disabled. Runtime validation rejects unknown tools,
arguments and aliases before secret retrieval; the native Gateway schema cannot
express every runtime restriction. Input/request bodies are limited to 16 KiB,
the secret to 64 KiB and provider responses to 1 MiB. Oversized responses fail,
not truncate. Provider HTTPS timeout is ten seconds, secret lookup has one-second
connect/read timeouts without retries, and Lambda timeout is fourteen seconds,
inside the adapter's fifteen-second read timeout. No transaction history persists.

`listItems` returns `{"items":[{"alias":"usaa","institution_name":"USAA","products":["transactions"]}]}`.
The configured aliases are `capital-one`, `usaa`, `amex`, and `empower`.
Provider tools return the sanitized native Plaid object. `getItemStatus` retains
safe Item error codes, consent metadata and provider freshness, adding
`configured_products`. Credential/token-like keys, raw error descriptions and
credential values echoed under unexpected keys are removed/redacted recursively.
Key-pattern filtering deliberately fails closed; matching future provider fields
are also omitted. Removals are not logged, to avoid retaining provider field names
or values. Consumers must not treat an omitted field as a zero or an empty value.
Bootstrap and runtime both reject duplicate JSON keys and nonfinite constants.
The deployed ZIP contains only `plaid.py`; `tools.json` is used by Terraform and
adapter catalog validation, not loaded by the runtime.
Failures return generic errors plus safe Plaid error codes/request IDs when present;
the runtime does not log payloads, credentials or raw exceptions.

Transaction dates must be real `YYYY-MM-DD` dates with `startDate <= endDate`.
`count` defaults to 100, range 1–500; `offset` defaults to zero, range
0–2147483647. Boolean integers are rejected. The provider receives the exact
requested offset. Results retain `total_transactions` and add `offset`, `count`
and top-level `next_offset` (integer while more data exists, otherwise null).
Use that exact next offset, not a guessed page number. Provider changes during
paging can change totals; this is a read view, not a durable snapshot.

All four existing Items currently consent only to `transactions`. Liabilities
requires configured `liabilities`; holdings requires `investments`. Recurring
requires `transactions` and may additionally require Plaid recurring entitlement.
No tool initializes a product, creates Link sessions, expands consent, updates
credentials or removes Items. Owner-only consent/Link lifecycle administration
is separate from these model-exposed reads.

## Owner activation

1. **Approve the privacy/retention decision before any live Plaid invocation.**
   Shared Gateway application body logging is active and can retain financial
   responses even though Lambda emits no payload logs. Review
   [Gateway log privacy](gateway-log-privacy.md). Explicitly approve that exposure
   and retention, or separately review/apply/verify stopping payload delivery
   before activation. This integration does not change shared logging. Stopping
   future delivery does not delete historical logs; deletion needs separate approval.
2. Review the TOOLS plan and apply the empty secret container, runtime, native
   target and its seven scope-bound Cedar permits with the normal owner deployment
   process. Do not deploy the new adapter checkout yet. Applying infrastructure
   does not import credentials or authorize live financial reads.
3. From a trusted owner shell, supply `PLAID_CLIENT_SECRET` through a secure
   environment source; do not put its value in arguments, shell history, chat or
   IaC. Reuse the existing production Items without new consent. The owner-only
   import helper validates the owner-only Item file, merges stored Items and
   checks the TOOLS account (`421680664125`). Preview, then explicitly write:

   ```sh
   python3 scripts/bootstrap/plaid.py import --secret-id /hermes/plaid/credentials --items-file /path/to/.plaid_items.json --client-id YOUR_CLIENT_ID
   python3 scripts/bootstrap/plaid.py import --secret-id /hermes/plaid/credentials --items-file /path/to/.plaid_items.json --client-id YOUR_CLIENT_ID --apply
   python3 scripts/bootstrap/plaid.py verify --secret-id /hermes/plaid/credentials
   ```

   Import is dry-run by default. Verify checks stored schema and reports only
   aliases/products; it does not prove live Plaid access. Secret JSON is strictly:

   ```json
   {"client_id":"...","secret":"...","items":{"capital-one":{"access_token":"...","institution_name":"Capital One","products":["transactions"]},"usaa":{"access_token":"...","institution_name":"USAA","products":["transactions"]},"amex":{"access_token":"...","institution_name":"Amex","products":["transactions"]},"empower":{"access_token":"...","institution_name":"Empower","products":["transactions"]}}}
   ```

4. Read back the applied Gateway catalog and permits: exactly the seven
   `plaid___` actions must exist alongside all existing targets. Only then deploy
   the new adapter revision with the normal adapter deployment process and verify
   its complete catalog, including all seven `plaid-` tools. Shipping this code
   does not switch the active adapter; strict catalog equality makes deploying
   the adapter before the target unsafe for existing clients.
5. With explicit live-read approval, check `plaid-listItems`, accounts, Item status
   and a bounded transaction page, including a nonzero offset. Compare totals and
   balances with the preserved owner baseline. Check unknown tools/arguments are
   denied. Unsupported liabilities/holdings must fail locally without provider
   calls. Recurring entitlement failures must not trigger consent expansion.
6. For an aggregate-only transaction overview, use
   `python3 scripts/plaid/overview.py --checkout /path/to/deployed/adapter-checkout --start YYYY-MM-DD --end YYYY-MM-DD`.
   The helper uses that checkout's isolated stdio adapter and only its four
   Gateway environment variables, not Plaid/AWS credentials. Optional `--output`
   creates a new owner-only file. It reads complete pages and checks totals;
   it does not establish full recurring/category/baseline-analysis parity.

Offline mocked Python and OpenTofu tests prove runtime dispatch, sanitization,
pagination and rendered infrastructure boundaries, not deployed IAM, ARM Lambda
execution, live Plaid entitlement, log suppression or production data parity.
Retain the external owner baseline and local fallback; local retirement and
upstream credential revocation require a separate explicit decision.

## Rollback and credential lifecycle

Restore the prior adapter revision first so its strict catalog no longer expects
Plaid. Then remove the Plaid target, Cedar permits and Gateway invocation grant
through a reviewed TOOLS plan if needed. Do not remove unrelated targets or
change shared logging as part of rollback. Preserve the secret and its recovery
window unless the owner explicitly requests deletion. Runtime role has no secret
write or Plaid mutation permissions. Credential repair/rotation is an owner-only
import with readback; account reauthentication or new Link administration is an
owner-only follow-up, not a chat tool.

Costs include the Secrets Manager container, requests, Lambda invocation and
CloudWatch/Gateway usage; lack of a database or NAT does not mean zero cost.
