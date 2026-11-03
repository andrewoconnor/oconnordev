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

## Operations and owner lifecycle

Before live reads, verify that the applied shared Gateway has no application-log
delivery connections. Follow [Gateway log privacy](gateway-log-privacy.md) to
check all deliveries and logging paths. Lambda does not log payloads, credentials
or raw exceptions; other logging paths may retain sensitive data.

Manage the TOOLS infrastructure through a reviewed plan. Apply the native target
and its seven Cedar permits before deploying an adapter revision that expects
those tools: adapter catalog validation is strict. Read back the Gateway catalog
and permits and verify the adapter catalog includes all seven `plaid-` tools.
Infrastructure applies do not populate the secret or authorize financial reads.

The owner manages credentials and Item configuration from a trusted shell. The
runtime role cannot write secrets or mutate Plaid data. Set `PLAID_CLIENT_SECRET`
through a secure environment source, never in arguments, shell history, chat or
IaC. The bootstrap helper checks the TOOLS account, validates the owner-supplied
Item file and merges stored Items. Import is dry-run by default; review the
preview before explicitly applying and verifying:

```sh
python3 scripts/bootstrap/plaid.py import --secret-id /hermes/plaid/credentials --items-file /path/to/owner-items.json --client-id YOUR_CLIENT_ID
python3 scripts/bootstrap/plaid.py import --secret-id /hermes/plaid/credentials --items-file /path/to/owner-items.json --client-id YOUR_CLIENT_ID --apply
python3 scripts/bootstrap/plaid.py verify --secret-id /hermes/plaid/credentials
```

Verification checks the stored schema and reports aliases and products, not live
provider access. The secret contains `client_id`, `secret`, and an `items` map;
each Item has an `access_token`, `institution_name`, and `products`. Credential
repair and rotation are owner-only operations. Account reauthentication, Link
administration and consent changes are owner-only and not exposed as model tools.

With explicit approval for live financial reads, check Item discovery, accounts,
Item status and a bounded transaction page including a nonzero offset. Unsupported
products must fail without provider calls; recurring entitlement errors do not
authorize expanding consent. Mocked tests do not prove deployed IAM, Lambda
execution, provider entitlement or live logging configuration.

For an aggregate-only transaction overview, run
`python3 scripts/plaid/overview.py --checkout /path/to/adapter-checkout --start YYYY-MM-DD --end YYYY-MM-DD`.
The helper uses the checkout's isolated stdio adapter and its four Gateway
environment variables, not Plaid or AWS credentials. Optional `--output` creates
a new owner-only file. It reads complete pages and checks totals.

For removal, review the TOOLS plan and coordinate adapter catalog changes with
target and permit changes. Do not remove unrelated targets or change shared
logging. Preserve the secret and its recovery window unless the owner explicitly
requests deletion. Costs include Secrets Manager, requests, Lambda invocation and
CloudWatch/Gateway usage.
