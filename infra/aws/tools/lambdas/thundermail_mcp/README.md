# Thundermail native read runtime

Native Rust `lambda_runtime` direct AgentCore Lambda target, restricted to
`oconnor@thundermail.com` on certificate-verified `mail.thundermail.com`.
No HTTP server, Node, Lambda Web Adapter, Himalaya or local config loaders.
Only `imap_list_mailboxes`, `imap_search_messages`, `imap_get_message` and
`caldav_list_events` are accepted; the native context names use `thundermail___` plus the raw tool name.
See [operations](../../../../../docs/runbooks/thundermail-mcp.md).

## Safety contract

Unknown tools/properties, invalid types, limits, mailbox control characters,
UIDs and malformed or mismatched cursors fail before secret retrieval.
`SecretStore` is get-only. The production implementation sends AWS SDK
`GetSecretValue` with the exact configured ARN and `AWSCURRENT` at invocation
time, never bootstrap. The ARN must match the invoked function's account/region
and `/hermes/thundermail/app-password` with its six-character AWS suffix.
Only Lambda execution-role environment credentials are used; no profile, IMDS,
STS, caller-provided endpoint, or credential-chain lookup. IAM separately limits
GetSecretValue to the one ARN.

The SecretString is a strict JSON object with `version` equal to `1` and
`password` containing a fresh dedicated owner-provisioned app password. No extra
keys, binary secret, control characters or empty passwords. The owner supplies
that value out of band; never copy a local mail credential or use a fixture value.
SDK errors and IMAP failures are redacted.

Every valid call has a five-second total deadline including secret lookup and
connection; provider lookup is capped at two seconds, upstream operations at
three. Decrypted IMAP I/O is limited to 262,144 received and 16,384 sent bytes.
Serialized output, including duplicated structured/text content and escaping,
is capped at 131,072 bytes. Large LIST/SEARCH responses fail closed rather than
providing unbounded enumeration.

Search/get use EXAMINE; fetch uses partial BODY.PEEK[] only. PEEK failure does
not retry BODY[], RFC822 or SELECT. No STORE or write tools. Get returns a lossy
UTF-8 raw-source prefix (16 KiB default; at most 65,536 requested bytes), not
MIME/attachment extraction. `possibly_truncated` is conservative.

Search supports only `all`/`unseen`, with descending UID pages bound to mailbox,
query and UIDVALIDITY. List uses a lexicographic name cursor. Cursors are strictly
validated untrusted data, not signatures or immutable snapshots; expunges and
renames can change later pages. No warm-process cursor cache. Plaintext loopback
endpoints exist only under `cfg(test)`.

## CalDAV

`caldav_list_events` sends one CalDAV `REPORT` `calendar-query` with a UTC
`time-range` to the fixed default calendar on port 443, with HTTP Basic auth.
It asks the server to expand recurring events. It returns UID, summary, start,
end, time zone IDs, location, status, description and recurrence fields, with
text truncated. The same transfer budget, five-second deadline and 128 KiB
output limit apply. `roxmltree` parses the multistatus XML and rejects DTDs.

## Container execution and health policy

The final image explicitly defaults to numeric `USER 10001:10001` for local
Docker runs. The bootstrap is mode `0755`; bundled notices are mode `0644`.
Neither ownership nor a passwd entry is required, so Lambda can also run the
image with a different least-privileged UID. The ARM64 `native_smoke.py` checks
the default user, file access with both the default and another UID, and actual
production-bootstrap invocation responses on a read-only filesystem.

The Dockerfile skips `CKV_DOCKER_2` because the runtime is a Lambda Runtime API
client with no listener. A Docker `HEALTHCHECK` cannot measure Lambda health.
See AWS's [Lambda image requirements](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html#images-reqs).

## Provenance

Selected MIT upstream: [tecnologicachile/mail-mcp](https://github.com/tecnologicachile/mail-mcp),
commit `da362f41fef8c0969b14b63e6bb5194b84e84549`.
`LICENSE.upstream` retains its actual notice. `extraction.json` records original
source hashes and inclusive spans: **149 original lines**, not the whole server
or unchanged upstream tool handlers. `upstream-read-closure.patch` discloses the
support adaptation; `connect.rs` separately attributes connection setup. Owned
code maintains validation, routing, budgets, provider, native entrypoint and tests.
Transitive versions are fixed by this crate's Cargo.lock, not asserted identical
to upstream's full dependency closure. TLS selects ring with defaults disabled.

Regenerate against an unmodified pinned upstream checkout:

```sh
python extract_upstream.py /path/to/mail-mcp "$(mise which rustfmt)"
```

## Verification

`mise run test:thundermail-rust` runs format, clippy and the locked tests. The
wire tests drive the real AWS SDK serializer and an IMAP fixture over loopback,
with no AWS or real mail. The image workflow runs `native_smoke.py` against the
built image, then publishes it to ECR without deployment.
