# Static-site module and mandatory state handoff

**Do not promote an ordinary plan after merging this refactor.** No AWS apply,
Spacelift setting change, state download/upload, or deployment was performed by
this change. The owner performs the following staged handoff. Both production
and resume have a default-false `site_state_handoff_complete` precondition:
normal plans intentionally fail until the owner confirms the state transfer.
`removed { lifecycle { destroy = false } }` protects all former production
site addresses even if a source detach is reviewed separately. Never remove
these declarations until the old addresses are verified absent.

## Ownership and why some resources stay in production

| Stack ID | Root | Ownership |
| --- | --- | --- |
| `oconnordev` | `infra/spacelift` | Existing administrative stack; **not** the resume stack |
| `oconnordev-production` | `infra/aws/production` | Shared oconnor.dev zone, KMS DNSSEC key/alias, KSK/DNSSEC, shared wildcard ACM certificate and validation, Hermes MCP endpoint and account services |
| `oconnordev-resume` | `infra/aws/oconnordev` | Existing resume bucket, distribution/OAC/headers, apex/www aliases and deploy IAM through the shared module |
| `drumrollworld` | `infra/aws/drumrollworld` | Existing DrumrollWorld zone/KSK/DNSSEC plus site module |

`mcp.oconnor.dev` currently uses `aws_acm_certificate_validation.oconnordev`.
Moving that wildcard certificate would either break Hermes or create a
production <-> resume dependency cycle. The certificate and validation records
therefore remain at their **unchanged production addresses**, alongside the
shared zone. The module manages DrumrollWorld's certificate and accepts the
production-exported certificate ARN for resume; neither introduces a new
certificate or second hosted zone for the resume.

Production exports `dnssec_key_arn` to **both** workloads, plus
`oconnordev_zone_id` and `oconnordev_certificate_arn` to resume. DrumrollWorld
uses the explicit key ARN, not `alias/dnssec`; resume's zone DNSSEC is still
managed by production. The GitHub repository configuration consumes resume's
role/distribution outputs after handoff. Production's old output names remain
compatibility aliases (the distribution ID is an explicitly overridable
compatibility input, not a competing resource). Existing broker trust and
physical AWS names/account/region are unchanged.

## Required bootstrap and ordered handoff (owner only)

1. Review the draft, then freeze/lock production, resume, DrumrollWorld and
   GitHub repository-configuration Spacelift runs and pause site-deploy jobs
   during state operations. Do not apply repository configuration while its
   newly wired resume outputs are still absent: empty inputs can otherwise
   propose removal of existing Actions variables. Disable
   run promotion as well as autodeploy; cancel queued runs and stale plans.
   Save every original backend state and stack/input configuration securely.
   State contains sensitive values: never commit it, attach it to a PR, or
   place it inside this repository. Use an owner-only directory (`umask 077`).
2. Review/apply the administrative stack **only**, to create the unique
   `oconnordev-resume` stack and its AWS integration/run ID wiring and explicit
   production dependencies. Do not reuse administrative ID `oconnordev`.
   Leave the new workload disabled/locked; creating an orchestration stack is
   not permission to create its AWS resources. The new root already has its
   lockfile. Existing `for_each` integration/context wiring includes it.
3. Publish the tested site releases containing `/404.html` to both existing
   buckets before enabling the error mappings. The resume release now emits
   this page with the same hashed local stylesheet, no inline CSS or script.
   Keep the existing distribution/role Actions variables unchanged.
4. Obtain authoritative current source state from `oconnordev-production`
   using the owner's authenticated Spacelift state workflow. Confirm account
   `767397796791`, region `us-east-1`, and all addresses in
   `scripts/infra/static-site-state-map.json`. Verify distribution
   `E2YPD9UPXXK53Y` and role
   `arn:aws:iam::767397796791:role/oconnordev-site-deploy` against this snapshot.
   Those two values were observed from the finished production run; remaining
   IDs **must come from state**, never guessed import IDs. The transfer moves
   13 resource declarations, including every indexed instance within them.
5. Export the destination's **empty** backend state. If the brand-new stack
   has never stored state, bootstrap an empty state through the owner's state
   workflow first: a separate, provider-free local directory with only
   `output "state_bootstrap" { value = "empty-resume-state" }` and
   `tofu init -backend=false; tofu apply -auto-approve` produces a v4 snapshot
   with a unique lineage and no managed resources or cloud effects. Upload
   that snapshot to the new, locked resume stack with the authenticated
   Spacelift state-management workflow, then download the stored snapshot.
   Never upload it to production. If the backend disallows empty-state
   bootstrap/export, stop and resolve that prerequisite; do not turn on the
   workload as a substitute. The transfer tool requires exact v4 exports with
   distinct lineages and rejects any destination managed resource.
6. Prepare **local copies only** (use paths outside the checkout):

   ```sh
   python3 scripts/infra/transfer_static_site_state.py \
     --source /secure/handoff/production-before.tfstate \
     --destination /secure/handoff/resume-empty.tfstate \
     --output-dir /secure/handoff/prepared \
     --acknowledge-stacks-locked
   ```

   The tool calls native `tofu state mv -state=... -state-out=...`, never an
   AWS API or backend write. It refuses missing addresses, deposed instances,
   duplicate ownership, reused output directories and changed lineages or
   provider payloads. Inputs remain unchanged. A **zero exit status and the
   completed `prepared/manifest.json` are mandatory** before either upload:
   verify its exact address map, resource count and `remote_changes: false`,
   then review both output snapshots. A failed/interrupted run can leave
   partially moved `prepared/*.tfstate` and sensitive backups. **Never upload
   any artifacts from such a run, even if they look plausible or both state
   files exist.** Missing manifest means incomplete preparation; preserve the
   originals and rerun into a new private directory after resolving the error.
   Compare retained zone, certificate, DNSSEC, Hermes, Config and account-service
   resources with the original source. The CLI's empty/absent `private` and
   empty/absent dependency-list serialization is normalized. OpenTofu 1.12.6
   clears an instance's **entire dependency list** in the destination when it
   references a source address being moved at that step. The tool predicts
   precisely this ordered reset: an instance can only be affected by its own
   move or subsequent moves, not earlier ones. Unaffected lists must remain
   exact, including references to shared resources and already-moved addresses.
   Native cross-state `state mv` does **not** remap those retained references;
   arbitrary remapping, injected edges, selective removal, or unrelated list
   removal fails validation. Fresh reviewed plans rebuild dependency metadata;
   do not treat state metadata as proof of the new configuration's wiring.
   All attributes/IDs, schema versions, sensitive-attribute paths, nonempty
   private data, provider addresses and indexed instance keys remain strict.
7. While **both backends remain frozen**, require the successful preparation
   and completion manifest above, and verify neither live snapshot's
   serial/lineage changed since export. Upload detached
   `prepared/production.tfstate` to production **first**, then adopted
   `prepared/resume.tfstate` to resume through the owner workflow. Do not
   use force or disable serial/lineage safeguards. This is a coordinated
   two-state operation, **not atomic**: if the second upload fails, keep all
   runs disabled and either retry against verified current snapshots or
   restore the original production state before any apply. Never leave two
   active owners or allow an intervening run. Re-download both states and
   verify the 13 addresses exist only at `module.site.*` in resume.
8. Only now set `TF_VAR_site_state_handoff_complete=true` for both roots.
   Keep production's existing nonempty `hermes_gateway_origin_hostname`
   dependency intact. Review a fresh production plan: only guard/output
   metadata may change; no site destroy/replace, no Hermes changes. Apply
   that reviewed plan to publish production's new key/zone/certificate
   outputs. Confirm the dependency references feed their exact ARNs/zone ID
   into both workload inputs. Missing upstream outputs are a bootstrap
   blocker, not something to fix with guessed values or an alias lookup.
9. Review fresh workload plans against transferred/real states. Resume:
   existing bucket/IAM/OAC/headers/distribution keep identities; expected
   changes are **in-place** compression, managed cache policy, 403/404 mapping
   and two new AAAA records. DrumrollWorld: `moved` declarations remap all
   existing site resources **within its original state**, including indexed
   certificate addresses; expected updates are managed cache policy and two
   AAAA records. Require **zero destroys and zero replacements**; inspect
   resource actions, not total change counts that include outputs. Never
   apply a create of an existing bucket, distribution, IAM role, certificate,
   validation record or A alias. Freeze and repair missing/incorrect state.
10. Owner applies only reviewed plans. Once resume has published its real
    unchanged role/distribution outputs, review the GitHub configuration plan
    before unfreezing that stack: existing Actions variables must retain their
    exact values, with no deletion caused by unresolved inputs. Then verify apex/www A and AAAA DNS,
    HTTPS headers, eligible Gzip/Brotli delivery, unknown paths returning
    `/404.html` with HTTP 404, both applications/PDF/gallery, MCP endpoint,
    and unchanged deploy-role/distribution Actions variables. Retain backups
    until fresh plans converge. Unfreeze deployments last. A revert of code
    alone cannot undo a cross-state transfer: restore ownership under the
    same locks before reverting, using inverse native state moves or verified
    snapshots with backend-approved serial handling, never an old stale plan.

No ordinary `moved` block can cross independent states. This procedure chooses
native explicit state transfer, so no import IDs need invention and ephemeral
ACM validation resources retain their state. The source non-destructive
`removed` declarations are defense in depth, not a completed handoff.

## Cache and routing behavior

Both sites inherit one delivery implementation: HTTPS redirect, OAC/SigV4,
TLSv1.2_2021, existing US/CA/GB/DE restriction and PriceClass_100, security
headers, and site-specific CSP passed byte-for-byte from the original roots.
A and AAAA each preserve **apex -> www -> existing distribution** routing.
Private S3 without ListBucket returns 403 for a missing object, so both 403 and
404 map to `/404.html`, HTTP **404**, error TTL **10 seconds**, never HTTP 200
or an SPA fallback. This intentionally also masks real origin permission
errors; investigate bucket/OAC policy if valid pages start returning 404.

AWS **Managed-CachingOptimized** ID is
`658327ea-f89d-4fab-a63d-7e88639e58f6`. It includes normalized Accept-Encoding
for Gzip/Brotli, no cookies/query strings, and policy TTLs **minimum 1s,
default 86400s, maximum 31536000s**. These necessarily replace legacy behavior
TTLs 0/3600/86400; declaring those legacy fields beside a managed policy does
not preserve their behavior. The existing publication script sets HTML/root
`public,max-age=0,must-revalidate`, hashed assets
`public,max-age=31536000,immutable`, then invalidates `/*`. HTML can still be
cached for at least 1 second; objects lacking Cache-Control inherit 24 hours.
Review cache headers for manually uploaded external images rather than assuming
old TTLs. [AWS policy documentation](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html).

## External image recovery risk (CKV_AWS_144)

The cheapest selected change is an **honest accepted-risk exception**, not paid
cross-region replication, a new backup bucket, AWS Backup, or an automatic
backup job. Repository code and generated resume assets are reproducible;
DrumrollWorld's externally maintained `images/*` master/derived photographs are
**not** fully reproduced from Git. Existing provenance catalogs cover only
captured inventories, not every unknown, changed or future upload; they cannot
prove a full historical archive exists. See the
[image-recovery runbook](runbooks/drumrollworld-image-recovery.md).

S3 versioning remains enabled; the existing lifecycle expires **noncurrent
versions after 30 days** and aborts incomplete multipart uploads after 7 days.
A deleted/overwritten photograph may be recoverable only while that noncurrent
version still exists. Versioning is not an independent backup; it does not
protect against lost account access, regional loss, version deletion by other
principals, or expiry of old versions. The deploy role's existing Deny on
`s3:DeleteObject` for `images/*` and the sync excludes reduce routine deployment
risk but do not cover PutObject overwrites, other credentials, or disaster loss.
No GetObject repair/read privilege is added to the deploy role.

Owner action, if stronger recovery is later desired: inventory original master
sources and provenance, confirm an independently held copy with checksums and a
restore test, then separately choose retention/storage/replication costs. This
PR does **not** claim such a backup exists and creates no billable backup
resources automatically.

## Evidence boundaries

`scripts/infra/test_static_site_state.py` uses real OpenTofu native state moves
on synthetic AWS-shaped snapshots, including native dependency-bearing moves
with indexed instances and opaque provider payloads. A separate dependency
fixture is genuinely generated by installed OpenTofu 1.12.6: it applies builtin
`terraform_data` resources with HCL references, verifies the emitted dependency
edges, then transfers that state natively. It proves ordered dependency resets
and exact retained edges, not a claim that synthetic AWS snapshots were imported
or generated by the AWS provider. Corruption tests reject changed attributes/IDs,
schema versions, sensitive paths, private data, provider addresses, instance keys,
injected/remapped edges and unrelated dependency removal. Failed preparation
leaves no completion manifest. Provider-free `terraform_data` plans projected
from every migration address also check retained shared objects,
missing-input/collision rejection, no-op moves and
forget-only removal with zero delete actions. Root `tofu test` mocks the locked
AWS provider to verify actual module inheritance, routing, errors, headers and
fail-closed guards. These are offline proofs of core state/configuration
semantics, **not** real imported state or a cloud-backed no-replacement plan.
The mandatory live snapshot and fresh plan gates above remain owner work.

### Local verification of this refactor

Actual execution with the repository-pinned tools and persistent provider cache:

- `mise run test`: exit 0. Python suites: 54 adapter, 22 rotation, 64 CI/policy,
  8 operational smoke tests; state fixtures: 6. Mock OpenTofu suites:
  DrumrollWorld 5, resume 6, production handoff/shared ownership 2, tools
  boundary 5, all passed. This includes negative handoff/alias cases.
- `python3 scripts/ci/validate_opentofu.py`: all **8 roots** passed using
  `init -backend=false -lockfile=readonly`; no live state or AWS credentials.
  The existing administrative `github_action_deploy` deprecation warning
  remains; it does not indicate a failed validation.
- Recursive OpenTofu fmt, actionlint, Ruff lint/format (45 Python files), Biome
  app lint/format and `git diff --check`: passed.
- TFLint 0.64.0 initialized the real AWS ruleset **0.49.0**, cached under the
  persistent home. Each of 8 roots plus the shared module passed explicit
  `--config=/absolute/repo/.tflint.hcl --enable-plugin=aws`; recursive lint also
  passed. Terraform's recommended preset is enabled. No compiler/toolchain
  install or environment sync was performed.
- Full Checkov 3.3.20 scan: Terraform **619 passed, 0 failed, 67 skipped**;
  GitHub Actions **280 passed, 0 failed, 0 skipped**. Skips are explicit risk
  exceptions, not a claim those protections exist.
- Fresh app builds and tests: resume **16/16**, DrumrollWorld **25/25** passed.
  Asset-pipeline suite: **17 passed, 4 optional real-tool tests skipped**;
  no ImageMagick/KTX compiler/tool installation was attempted.
- Actual-HCL CSP/Permissions browser regression: all **5 modes** passed
  (resume and resume 404; Drumroll globe, WebGL-unavailable and 404), zero
  compatibility CSP violations/page errors, foreign/inline attacks blocked,
  **11 genuine KTX2 worker transcodes** for this runner's GPU ceiling.
  Existing background-upgrade browser regression also exited 0. Genuine
  previously available encoded fixtures were reused; no production artwork
  or browser/CDN performance guarantee is inferred from them.

All results above are local/offline. No state handoff, registry publication,
Spacelift/AWS apply, paid backup, or live deployment has occurred.

### Dependency-bearing migration regression verification

The original six migration tests did not include state dependency metadata.
The dependency-bearing AWS-shaped native-move regression first failed with
`Instance bytes changed at aws_cloudfront_distribution.oconnordev`; after the
narrow ordered-reset fix, the focused suite passes **11/11**. The generated
builtin-provider fixture above demonstrates actual OpenTofu-emitted dependency
edges, not manually injected metadata. Provider-address corruption also failed
its new rejection test before the explicit preservation check was added.

The complete `mise` test dependency graph was rerun successfully using a
scratch-only cached-tools configuration. All repository test commands and
suite dependencies were retained; only the task's `pip install` prerequisite
was replaced by an assertion that already-installed `cedarpy==4.12.1` matches
its pin. No package/tool installation was run. Results: Python **54, 22, 64,
8** tests; OpenTofu tools **5**, DrumrollWorld **5**, resume **6**, production
**2**; migration **11**, all passed. Focused Ruff lint/format, recursive OpenTofu
formatting, actionlint and `git diff --check` also passed. No live snapshots,
backend operations, AWS calls or commits were used for this regression fix.
