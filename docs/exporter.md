# Metadata-only Langfuse exporter (#8)

## Contract

One immutable root `GENERATION` per ingress, using **the persisted**
`IngressRequest.trace_id` and `generation_id`. No synthetic parent, early generation,
generation update, provider replay, or CPA usage-queue reads. Original ingress/end
timestamps describe model latency, never export delay.

Langfuse v4.69.0 same-ID enrichment produced duplicate visible observations in the
disposable live experiment. IDs provide local uniqueness and remote correlation,
**not remote exactly-once delivery**. Freeze payload bytes at the first committed
attempt, including attempts that later prove safe to retry. A remote-accepted/local-
unacknowledged attempt cannot safely be resent automatically.

Write path: `POST /api/public/otel/v1/traces`, HTTP/JSON, project Basic auth from
separate public/secret key files, `x-langfuse-ingestion-version: 4`. One span per
request. No legacy ingestion endpoint. HTTP 200 acknowledges queued ingestion,
not visible persistence. The response may be a queue-job object rather than `{}`.

## Public interfaces and #6 wiring

Files: `exporter.py` (typed snapshot/serialization), `exporter_settings.py`,
`exporter_repository.py`, `exporter_transport.py`, `exporter_worker.py`, migration
`008_exporter.sql`. No lifecycle-table dependency or application startup wiring.

1. Run `await Database.migrate()` at worker startup. Instantiate
   `ExporterSettings(enabled=True, destination=..., base_url=...,
   public_key_file=Path(...), secret_key_file=Path(...))`. Disabled is the default;
   settings are deliberately independent of shared application configuration.
2. #6 must scan committed completed gateway lineage, join only current unambiguous
   proof-gated projection data, and construct `Observation` explicitly. Never pass
   inbound dictionaries, arbitrary metadata, raw CPAMP rows or body/header objects.
   Scan retained completions on restart and with overlap. An enqueue failure must
   leave the source eligible for later scanning; never repair telemetry by replaying
   the model request. Source/scan cursor wiring and crash-gap acceptance are #6 work.
3. `await ExportRepository(db, settings).enqueue(observation, now=None)` upserts one
   request. With proof disabled (current production gate), finalizes gateway-only
   `READY` immediately with `usage_unproven`, `proof_disabled`, absent tokens/cost.
   Proven complete correlated usage is immediately ready. Proven but incomplete
   usage waits up to `usage_wait_seconds`; the stored partial snapshot then becomes
   ready with explicit `usage_timeout`. Rescans do not extend that deadline.
4. `await repo.finalize(observation, reason=..., now=None)` explicitly finalizes or
   replaces an **unattempted** snapshot. Allowed reasons: `proof_disabled`,
   `usage_complete`, `usage_timeout`, `gateway_only`. Before claim, enrichment and
   claim serialize through row locks. After claim, changed snapshots set sticky
   `remote_snapshot_stale=true` and `late_payload_hash`; bytes/IDs remain frozen.
   Identical replay is a no-op. The authoritative projection keeps the full late
   correction; this module stores only its safe hash, not a second observation.
5. In a dedicated worker, call
   `await ExportWorker(repo, OtlpTransport(settings)).drain(limit=100)` periodically.
   It performs at most `limit` attempts, stores retry times, and never sleeps for
   backoff. Do not invoke `drain` from the provider response/stream path. Enqueue
   has no HTTP dependency. Stalled-ingestion tests demonstrate independent repository
   access, but actual gateway-response isolation awaits #6 end-to-end wiring.
6. `await repo.recover(now=None)` scans outbox state on startup/periodically; `claim`
   also calls it. Expired in-flight leases become `UNCERTAIN`. Waiting deadlines,
   retry caps and age expiry are enforced. `claim`, `lease_active`, `finish` are
   low-level worker seams, not end-user routes. Each claim commits attempt count,
   token and expiry before HTTP; `finish` requires the same unexpired token.
7. Expose `await repo.stats()` only through operator-authorized health/diagnostics.
   It returns enabled flag, state counts, bytes/rows, oldest pending age, late-change
   count, and durable capacity/age/identity/pruning counters. `await repo.get(UUID)`
   returns job status/hash, attempts, next attempt/expiry and safe reason code; it
   never returns credentials, raw response text or payload bytes.
8. Schedule `await repo.prune(now=None, limit=1000)` for bounded local retention.
   Strict cutoff: request start **< now − retention_seconds**; default 90 days.
   Terminal dedup rows remain until this cutoff, and expired source inputs cannot
   recreate them. #6 must coordinate lineage/projection retention and remote cleanup.

`destination` is a stable, trusted configuration identity for exactly one Langfuse
project. Never change its project/host association while retaining its outbox. Keep
one consistent settings policy across its workers. Clock injection is for tests;
deployed workers require synchronized UTC clocks. A fence prevents stale local
acknowledgements, but cannot stop a process suspended after its final pre-send check;
no second worker resends an expired lease, preserving the conservative policy.

### Snapshot fields and boundaries

- `ingress`: committed server-generated UUIDv4 and original trace/generation IDs,
  stable ownership, original accepted time and safe session. No ID rederivation.
- `ended_at`, `endpoint` (`responses`, `chat_completions`, `completions`, `embeddings`),
  `outcome` (`succeeded`, `failed`, `cancelled`, `timeout`, `unknown`), optional numeric
  HTTP status; requested/resolved model and provider are separate bounded labels.
- `principal: Principal | None`: #5's verified principal at ingress, matched to
  ingress issuer/subject and its original verification/expiry interval. Current
  expiry at export is irrelevant. Omit for machine-only access; never use key creator
  as user. `Ownership.subject` alone does not certify human verification. A restart
  adapter must retain validated evidence or omit user; do not fabricate a Principal.
- Session allowlist: 1–128 ASCII alphanumeric/`_.-`, first character alphanumeric;
  otherwise fallback to generated ingress request ID. Gateway owns whether a caller
  session is permitted at all. Current ingress factory always generates it.
- `binding: NativeBinding | None`, `correlation: CorrelationResult | None`: shared
  #3 validator checks ownership/native-ID agreement. Export CPA instance/full native
  UUID and CPAMP instance/event hash, never the returned trace's auth-index text.
- `usage_gate` defaults to #3's hard-disabled production gate. Tests can inject a
  synthetic enabled gate solely to exercise future mapping. #6 must use the actual
  proof result, never an environment boolean to bypass the release gate.
- `ExclusiveUsage`: already-normalized `input`, `input_cached_tokens`,
  `input_cache_creation_tokens`, `output`, `output_reasoning_tokens`, `total`, and
  `normalization_version`. Mapping from #4/#10 buckets: `input_uncached -> input`,
  `cache_read -> input_cached_tokens`, `cache_write -> input_cache_creation_tokens`,
  `output_nonreasoning -> output`, `reasoning -> output_reasoning_tokens`,
  `total_tokens -> total`. Do not normalize inclusive totals twice. Missing values
  remain missing. Only verified complete exclusive buckets whose sum equals total
  become native usage. Partial safe counts stay metadata to avoid a fabricated sink
  total. Duplicate/ambiguous/noncorrelated rows never provide usage or cost.
- `ExportCost`: amount/currency/classification/pricing version/source. Native cost
  exports only known USD; known zero is valid, unknown is absent. Classification
  defaults unknown; provided amounts require estimated/authoritative, and authoritative
  requires source evidence. Non-USD currency/provenance are labeled, not converted.
  Langfuse may infer estimated cost from a recognized model and usage even when no
  cost was supplied. Every payload labels that possibility explicitly; sink cost is
  never CPAMP billing authority. Local amount stays unknown rather than zero.

The serializer has no input/output/prompt/tool/header/error-body/arbitrary metadata
field. Resource/scope attributes are constants. Credential files are bounded-read
and never enter rows/payloads/repr; errors use fixed codes. Allowed labels are a
schema boundary, not a detector for a secret deliberately put into an allowed model
or ID field: adapters must source them from validated policy/lineage/projection.

## Delivery outcomes

| Outcome | State / policy |
|---|---|
| 200 bounded JSON object, no partial rejection | `ACCEPTED`; unknown queue-job fields tolerated |
| Valid `partialSuccess`, absent/zero rejected count | `ACCEPTED`, warning code if message present; raw message discarded |
| Exactly one rejected span | `DEAD_LETTER/partial_rejection`; never retry |
| Malformed/nonobject/truncated/oversized/compressed 200, duplicate JSON keys, impossible count | `UNCERTAIN`; never infer nonacceptance |
| Connection establishment failure/timeout, pool timeout before send | `RETRY_WAIT` |
| 429 | `UNCERTAIN` by default; retry only when `trusted_pre_admission_429=True` is backed by destination-specific evidence |
| Read/write timeout, post-write disconnect, cancellation, expired lease, 408 or any 5xx | `UNCERTAIN`; no automatic retry |
| Other 4xx or missing/invalid credential files | `DEAD_LETTER` with redacted code |
| Other 2xx or redirect | `UNCERTAIN`; never redirect credentials |

OTLP allows retrying 502/503/504, but a proxy failure can occur after acceptance;
this implementation deliberately chooses conservative uncertainty. Safe retries use
identical bytes and jittered exponential delay: base 1 second, cap 300 seconds,
minimum 100 ms (no hot loop), max 10 attempts. Trusted 429 honors `Retry-After`
seconds/HTTP date as a minimum. If the next attempt exceeds the request-start age
limit (24 hours), dead-letter rather than retry earlier. Default total HTTP timeout
10 seconds, lease 60 seconds. Database commit failure leaves the lease recoverable
as uncertainty; no new send occurs to repair an acknowledgement.

Default caps: 32 KiB payload, 64 KiB response, 100,000 rows and 256 MiB serialized
payload per destination. Rows include accepted/dead/uncertain dedup evidence;
PostgreSQL/index overhead is additional. Capacity admission is transactionally
serialized; no silent pending-row eviction. Aggregate suppression counters persist;
the #6 scanner must retain per-source retry eligibility. O(N) spool accounting per
enqueue is intentionally simple for Phase 1, not a high-throughput design claim.

No automatic uncertain replay or readback reconciliation is implemented. Operators
may inspect v2 observations using exact trace/span and original time bounds; absence
does not establish nonacceptance. Authentication failures are terminal per job;
destination-wide pause/control and an operator repair workflow remain integration
work. Local pruning does not delete remote observations. Built-in self-hosted remote
retention is Enterprise-gated; OSS needs explicit supported API trace cleanup and
independent blob lifecycle. Do not claim 90-day remote retention from this module.

## Validation / reproduction

`tests/test_exporter.py` uses real disposable PostgreSQL via
`PROXYLENS_EXPORTER_TEST_DSN`; it applies production migrations and truncates only
exporter tables in that dedicated database. Do not target a shared production DB.
Only external HTTP/time are controlled. Tests cover leases/races/restart (including
independent interpreter exit), payload freeze, enrichment, byte/row/attempt/age caps,
redaction, identity mismatch, partial success, timeout/disconnect/cancellation and
trusted throttling. Failure scripts do not call providers.

`scripts/langfuse-export-poc.py` takes `--base-url`, `--public-key-file`,
`--secret-key-file`, `--output`; reads its DB DSN from the variable above. Run with
`PYTHONPATH=src` in the supported Python 3.12 environment. It creates fresh synthetic
IDs, enqueues gateway-only unproven usage, proves real connection refusal then
durable recovery, reads v2 observations, verifies one root and absent content/usage,
and checks replay/late enrichment creates no additional planned send. v4.69.0
returns omitted machine `userId` as an empty string.

`--malformed-success` additionally forwards to the actual sink, corrupts only its
acknowledgement, and verifies local `UNCERTAIN/malformed_success` while exactly one
generation is remotely visible. This is deliberate fault injection, not a claim
that Langfuse natively emits malformed success. The worker never resends it.

Live check 2026-10-26: `docs/evidence/exporter-v4.69.0.json`. Disposable endpoint
v4.69.0, real PostgreSQL, one visible root after safe retry; no provider requests,
fabricated usage or provider OAuth. Prior sink experiment separately demonstrated
same-ID enrichment duplicates and accepted malformed-success ambiguity. This ticket
does **not** close gateway lifecycle wiring, live CPA→CPAMP proof, end-to-end latency,
remote retention, power-loss recovery or exactly-once remote delivery.
Malformed-ack evidence: `docs/evidence/exporter-v4.69.0-uncertain.json`.
