# Request lineage contract (#3)

## Status and evidence

**Live native correlation partially demonstrated; tenant usage disabled.**
`docs/evidence/issue-3-correlation.json` records the gate, pins, provenance and
remaining scenarios. It is an evidence record, not an operator-editable enable switch.
`tenant_usage_gate()` cannot be enabled by environment variables, fixtures or a
history-only proof. A future evidence-reviewed change must establish both live
correlation and durable-history compatibility for the deployed versions.

Pinned contract: CLIProxyAPI **v8.0.40**, source
`d946c4fba6fc9a5cfbca1f3d85184d62ad2fb683`; CPAMP **v1.14.9**, source
`6d962db680085827cd19a778d2ff05a3d1315672`.
Detailed source coordinates and the isolated synthetic HTTP experiment:
`/data/tmp/opencode/proxylens-phase1/contracts.md`, sections 4 and 6;
acceptance scenarios: adjacent `acceptance.md`, especially 7.3, 7.8–7.9,
10.1–10.4, 8.4–8.7 and the live-evidence matrix.

The continuation harness has now exercised authorized Codex Responses execution
through the actual gateway with two synthetic Keycloak groups and one shared
CPA-managed Codex credential. Non-streaming, streaming, function-tool and
synthetic-image requests each produced an exact native UUID → CPAMP event-hash
join, separate immutable group/application ownership, and visibility within the
60-second target. A bounded cancellation produced the native binding and a
gateway `cancelled` lifecycle row but no CPAMP durable event; no usage was
assigned. Retry/failover, native-ID collision, outage/restart/retention
completeness and the full independently reviewed proof pair remain unproven.
Tenant usage therefore stays disabled. Source inspection and synthetic CPAMP
imports remain insufficient by themselves.

## Identity and lifecycle

1. Gateway resolves client key, application, stable Keycloak group and issuer from
   trusted authorization state. `Ownership` is an immutable snapshot of those
   references, optionally including a verified human subject. It does not verify
   authorization or create an identity/group authority.
2. `IngressRequest.new(owner)` generates a UUIDv4 per invocation, UTC acceptance
   time, independent trace ID (32 hex), generation/span ID (16 hex) and request-ID
   session fallback. Repeated caller request IDs have no effect; caller IDs are not
   inputs. The same IDs must be reused for later observation enrichment.
3. Commit `LineageRepository.record_ingress(request)` **before** dispatch. A write
   failure must prevent provider dispatch. Resource/policy validation and its audit
   transaction remain #9/#7 responsibilities. No resource foreign keys are invented
   here; immutable ownership snapshots retain historical references after deletion.
4. `propagation_headers(request)` returns only generated `X-Request-ID`. The
   gateway builds an outgoing allowlist and adds its service CPA client credential;
   it must not merge arbitrary inbound headers. No model payload mutation is needed.
   This header is diagnostic: CPA generates its own native ID independently.
5. On response headers, pass `response.headers.multi_items()` to
   `bind_response(request_id, configured_cpa_instance, headers)` and commit before
   forwarding response bytes. Use the configured CPA response only, never client
   headers or an unrelated upstream. The routine preserves full native UUIDv7,
   not the eight-character log suffix. It discards the raw header and account index
   after parsing. It returns `partial`, `missing` or `ambiguous` as a diagnostic snapshot.
6. #4's read adapter supplies `UsageIdentity.from_cpamp(cpamp_instance_id,
   event_hash, cpa_instance_id, request_id)`. The instance pairing is trusted
   deployment configuration. #10 calls `record_event()` and queries current
   `resolve_event()` or `lineage_event_resolution` before scoped publication.
7. #7 owns forwarded/header/completed timestamps, transport status, terminal SSE
   outcome, cancellation and timeout lifecycle. Header persistence failure after
   dispatch remains an uncertain/partial request; **never replay the provider to
   repair lineage**. No gateway routes or lifecycle state machine are installed here.

## Returned-ID grammar and limits

`X-CPA-TRACE-ID = 14 ASCII digits + '-' + opaque auth index + '-' + full UUIDv7`.
ProxyLens accepts a bounded safe index alphabet `[A-Za-z0-9_.]`, length 1–64,
and the pinned lowercase RFC-variant UUIDv7 spelling; entire header ≤116 characters.
Other spellings/formats fail closed. This is a compatibility boundary to revisit
with pin upgrades, not a claim that arbitrary future CPA formats are supported.
The timestamp prefix is selection-local time, never a join key or watermark.
Duplicate header occurrences (even identical), comma-combined headers, controls,
missing/short/invalid IDs and oversize values return no mapping. Invalid values
are neither retained nor echoed in errors.

CPA's `internal/logging/cpa_trace.go` constructs this header; its queue publisher
`internal/redisqueue/plugin.go` exposes the same native request UUID. CPAMP preserves
`request_id` in analytics/export. CPAMP's SQLite integer row ID is not returned;
the public durable identity is **`(cpamp_instance_id, event_hash)`**.

Do not substitute Responses `response.id`, upstream `X-Request-Id`, CPAMP
`header_trace_id`, request timestamps, model similarity, API-key/account hashes,
or the header's selected auth index. Retry attempts may use different provider
accounts but share one native UUID. All distinct event hashes must survive.
`X-Client-Request-Id` and `Session-Id` can affect Codex affinity; this helper does
not repurpose them. Arbitrary metadata is not a proven queue echo channel.

## Persistence and status semantics

Production SQL is bundled at `src/proxylens/migrations/003_lineage.sql` and included
by the existing Dockerfile's `COPY src`. Run `apply_lineage_migration(connection)`
in the deployment migration transaction before gateway/worker startup; it is
repeatable. Startup wiring is intentionally left to #7/#10's migration orchestration.

| Relation | Contract |
|---|---|
| `lineage_ingress` | One generated request ID; immutable ownership and observation IDs. Re-insertion fails rather than updating another invocation. |
| `lineage_native_binding` | `(cpa_instance, native UUID, ingress UUID)` claims, including conflicting claims. Same claim is idempotent. One ingress may have multiple native invocations; gateway retry rules remain separate. |
| `lineage_usage_event` | One row per CPAMP instance/hash, optional native UUID, first-seen time, sticky conflict bit. No tokens, raw content, account metadata or credentials. |
| `lineage_event_resolution` | Current join and status. Only exactly one ingress claim yields an owner. Later collisions invalidate earlier rows automatically. |

| Status | Meaning |
|---|---|
| `correlated` | Structurally exact native-ID match with one immutable ingress owner; **not** live-provider proof or permission to publish. |
| `partial` | Native ID exists but no ingress binding; at the header boundary, binding exists but CPAMP arrival is not established. |
| `missing` | Native ID absent/invalid. No ownership guesses. |
| `duplicate` | `record_event()` observed an identical CPAMP hash replay. It returns no countable owner. Durable row keeps its underlying current status. |
| `ambiguous` | Multiple ingress claims, including same-owner distinct requests, or conflicting source identity for one CPAMP hash. No owner; takes precedence over duplicate. |

`record_event()` atomically inserts/deduplicates and resolves; inside an outer
transaction it uses a savepoint, otherwise it commits its own transaction. Caller
transactions should include projection updates/cursors. Other repository writes
rely on the caller's commit. Use normal PostgreSQL READ COMMITTED and fresh reads
for publication. Returned dataclasses and transaction snapshots can become stale.

**#10 must join current `lineage_event_resolution` at read time** (or implement
equivalent atomic invalidation) for lists, counts, totals and details. Copying a
previously resolved group into usage rows and trusting it forever is invalid.
Re-resolve before observation enrichment too. Never delete conflicting claims to
make attribution succeed. Future retention must preserve collision/dedup evidence
for the full projected-history lifetime; the foreign key currently prevents
deleting an ingress with retained bindings.

## Observability and fallback

`observation_metadata(request, result=None, *, binding=None)` produces a strict
metadata allowlist, not an OTLP payload. An optional gateway binding exposes the
native ID before usage arrives (`partial`); a resolved result adds CPAMP identity.
It rejects a different ingress owner and conflicting native IDs. Ambiguous,
missing and duplicate events carry no ingress and cannot be attached to a tenant
observation. #8 maps verified subject to `userId`, generated session to `sessionId`,
and stable trace/generation IDs to its wire format. For machine requests, no human
`userId` is fabricated. No key-creator identity, raw header, auth index, arbitrary
metadata, prompt/output, failure body or credential is accepted by this exporter seam.
Actual Langfuse delivery belongs to #8 and is not demonstrated by serialization tests.

Missing response headers cannot be repaired deterministically using a shared key
and time/model/usage similarity. Distinct upstream application credentials could
provide coarse ownership, but still cannot identify an individual request/attempt.
No fallback architecture is selected before the native-header POC, so no new ADR
is warranted yet.

## Validation

Run the locked environment, then:

```sh
PROXYLENS_TEST_DATABASE_URL='<isolated PostgreSQL DSN>' .venv/bin/pytest tests/test_correlation.py tests/test_lineage.py
```

Tests create/drop unique schemas in the supplied test database, exercise actual
production SQL and independent connections, and use no mocked repositories.
They cover parsing bounds, full IDs, owner/instance isolation, retry event hashes,
replays, sticky conflict, late collision invalidation, concurrency, reconnection,
rollback, late header arrival, safe metadata, and the disabled gate. Without a
DSN, PostgreSQL tests skip explicitly; unit tests are never live-provider evidence.
