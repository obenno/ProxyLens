# CPAMP durable-history adapter — v1.14.9

> **Current implementation / original #4.** This CPAMP-specific contract remains
> useful for optional diagnostics in revised #3. Candidate usage checks consolidate
> into #7 under the [integration plan](specs/litellm-poc.md).

Issue #4. Implementation: `src/proxylens/cpamp.py`. CPAMP Full Mode remains the
authoritative durable history and sole CPA usage-queue consumer. This adapter
uses three read-only HTTP operations. No SQLite fallback or queue client exists.

## Pin and evidence

- CPAMP release `v1.14.9`, source `6d962db680085827cd19a778d2ff05a3d1315672`.
- Official Linux amd64 archive `cpa-manager-plus_v1.14.9_linux_amd64.tar.gz`:
  SHA-256 `d3d2d4977bbfded997656d3a65fe8f405890312c2e4a595359c5af675f029455`.
- Adapter accepts only the configured version above. HTTP history/status does not
  attest a binary version; deployment must verify the release/digest independently.
- Panel-facing upstream APIs are implemented contracts at this pin, not a promised
  stable public SDK. Schema mismatch fails explicitly; upgrades require fixture and
  released-binary revalidation.
- `tests/fixtures/cpamp-v1.14.9/` contains portable, synthetic release responses.
  `docs/evidence/cpamp-v1.14.9.json` records the executed adapter POC summary.
- The session date is October 24, 2026; the runtime evidence clock was October 23,
  2026 UTC. Evidence preserves that clock rather than relabeling timestamps.

Controlling source coordinates (all relative to `apps/manager-server/` at the SHA):

| Contract | Source |
|---|---|
| Authentication | `internal/service/adminauth/service.go:21-42`, `internal/http/middleware/auth.go:34-61` |
| HTTP reads/export | `internal/http/controller/usage/handler.go:31-104,629-640` |
| Request/filter/page schema | `internal/service/monitoring/service.go:117-229,851-911` |
| Keyset ordering and normalized analytics fields | `internal/repository/usagemonitoring/event_page_read.go:51-204` |
| Snapshot export and raw fields | `internal/repository/usageevent/stream.go:389-491,597-623,747-886` |
| Durable schema and identity | `internal/repository/sqlite/migrate.go:232-299`, `internal/usage/event.go:1317-1344` |
| Retention coverage | `internal/service/monitoring/service.go:1553-1695` |
| Cache/total normalization | `internal/usage/event.go:283-305,558-600,722-745,807-935` |
| Collector diagnostics | `internal/collector/collector.go:22-34,411-453`, `internal/http/controller/system/handler.go:43-98` |

Pinned source base:

```text
https://github.com/seakee/CPA-Manager-Plus/tree/6d962db680085827cd19a778d2ff05a3d1315672/apps/manager-server
```

## Public Python interface

```python
from proxylens.cpamp import CPAMPAdapter, HistoryWindow

async with CPAMPAdapter(
    cpamp_origin,
    server_side_admin_key,
    instance_id="deployment-stable-cpamp-id",
    cpamp_version="v1.14.9",
) as adapter:
    result = await adapter.read_window(
        HistoryWindow(
            from_ms,
            to_ms,
            providers=("codex",),
            include_failed=True,
        )
    )
    diagnostics = await adapter.read_status()  # optional; no usage read watermark
    health = adapter.health(expected_pending_since_ms=oldest_unmatched_request_ms)
    # Stage result.records with identity-based upserts. Inspect state/reasons first.
```

`read_window` and `read_export` return `ReadResult`: records, state, fixed reason
codes, page/rejected/duplicate counts, response generation time where available,
coverage, `traversal_complete`, and `snapshot_verified` (always false at this pin).
Partial rows on error are diagnostic/staging candidates; never replace a good
projection with them. There is no resumable adapter cursor: retry the fixed window
and deduplicate. Do not reuse a cursor with changed window/filter parameters.

`UsageRecord.identity` is **`(instance_id, event_hash)`**. Configure the instance ID
persistently; change it when replacing CPAMP with an unrelated store. A repeated
native `request_id` can name several attempts; it is not the dedup key. Duplicate
hashes within one traversal are counted and emitted once. Conflicting sanitized
records with one hash quarantine both. The adapter retains bounded sanitized
conflict identity before applying exact request filtering, so quarantine is
independent of page/order and cannot be bypassed by a nonmatching search result
arriving first. Dedup across calls/restarts belongs to the durable projection,
not this bounded in-memory adapter.

One adapter per polling task, sequential calls. Client ownership is scoped by
`async with`; cancellation propagates and closes the response. No retries or
background polling are hidden inside the adapter. In the worker integration,
the projection polling task and operations supervisor each receive a separate
adapter constructed from the same server-side key. The supervisor adapter owns
readiness history/status state; the projection adapter owns projection polling
state. Their HTTP reads are both read-only and neither consumes the CPA queue.
This module is not wired into tenant endpoints by this issue.

## HTTP contracts

All requests use CPAMP's own origin and `Authorization: Bearer <CPAMP_ADMIN_KEY>`.
This is its manager key, not CPA's Management API key. The credential grants admin
capabilities upstream: there is no proven read-only/user-scoped token. It stays
server-side. Redirects, URL credentials/query/path, environment proxies, and
compressed responses are rejected/disabled. The adapter has no arbitrary route API.

### Filtered history

`POST /v0/management/monitoring/analytics` is read-only despite POST:

```json
{
  "from_ms": 1792800000000,
  "to_ms": 1792886400000,
  "time_zone": "UTC",
  "filters": {"providers": ["codex"], "include_failed": true},
  "include": {"events_page": {"limit": 500}}
}
```

- Positive integer millisecond interval **[from_ms, to_ms)**. This adapter exposes
  provider/model tuple filters, failure inclusion, and exact native request-ID
  lookup. Upstream has other filters; they are not silently accepted by this API.
- `events.items` order is timestamp descending, SQLite ID descending. With
  `has_more=true`, copy **both** `next_before_ms` and `next_before_id` into
  `include.events_page.before_ms/before_id`. The latter is a cursor, not a row ID.
- Strictly decreasing cursor tuples, ordered timestamps, terminal zero cursors,
  nonempty continuation pages, response shape/types and page sizes are checked.
- Request-ID lookup uses top-level `search_query` as a narrowing hint, followed by
  exact returned `request_id` comparison. Upstream search is substring/SQL LIKE;
  there is no upstream exact `request_ids` filter. No auth-index narrowing is
  applied to request IDs because it could discard retry/failover attempts.
- `total_count` changes/mismatches degrade the read. It is not an atomic snapshot
  count across pages. `generated_at_ms` is response-generation time, not ingestion
  progress or event completeness. New inserts can land before a consumed cursor.
- Use overlapping fixed windows and periodic retained-history reconciliation.
  Event time is not ingestion time. No finite overlap guarantees discovery of
  arbitrarily late imports; persisting the highest event timestamp is insufficient.

### Snapshot candidate

`GET /v0/management/usage/export` returns JSONL of retained raw rows. It ignores
query filters/limits and UI QueryLimit. The adapter intentionally accepts no export
filters/cursor. Upstream holds a read transaction and internally batches 512 rows,
ascending timestamp/ID; those internal cursors are not HTTP pagination.

EOF with complete newline-terminated JSON rows means only that transport traversal
finished. Upstream can encounter a storage error after starting a 200 response and
return a valid-line prefix; there is no footer count/checkpoint. Thus every export
is `degraded` with `export_completeness_unverifiable`, `snapshot_verified=false`.
Keep rebuild staging separate; independent reconciliation/operational evidence is
required before destructive replacement. A missing final newline is
`truncated_export`; malformed lines are counted, skipped, and explicitly degrade.

### Persistence, retention and health

CPAMP stores `usage_events` in SQLite (default dataDir/usage.sqlite), with internal
autoincrement `id` and unique `event_hash`. The HTTP surfaces read durable rows,
not the consumptive queue. `GET /v0/management/usage` is UI-limited and lacks the
needed record identity; it is deliberately unused.

Raw retention is disabled by default; when enabled upstream defaults to 30 days.
Aggregates can survive deleted raw rows. Analytics `coverage.raw_complete=false`
or deleted counts causes `retention_gap`; preserve scope/mode/count/range facts.
Absent coverage is no known archive warning, **not proof of no collection loss**.
Export cannot replay archived/deleted event details. Archive status endpoints are
not a downloadable event-replay interface.

`GET /status` optionally reads only collector state, last consumed/inserted times,
dead-letter count, and error presence. No raw error, upstream URL or database path
is returned. A stopped collector, error or dead letters degrades health. Old/zero
insertion time alone does not imply failure on an idle deployment; upstream also
updates that time on duplicate processing. Runtime counters are not a durable
producer acknowledgment/sequence ledger. Queue expiry/pop-to-insert losses remain
unmeasurable without upstream reconciliation; ProxyLens never probes that queue.

| State | Adapter meaning |
|---|---|
| available | Completed analytics traversal, no detected defects; not a tenant completeness claim |
| stale | Last clean analytics read older than 60 seconds, or caller reports expected-request lag beyond 60 seconds |
| degraded | Retention, malformed/missing-ID rows, unknown/inconsistent normalization, duplicates/conflicts, count drift, export uncertainty, or collector defects |
| unavailable | Not read, auth/transport/HTTP/schema/cursor failure or safety limit reached |

`health()` combines most recent read and sampled collector conditions. Severity is
unavailable > degraded > stale > available; lag reasons still accompany degraded
health. A successful status probe does not refresh history freshness. A new history
read does not erase sampled collector faults; re-probe to clear them. `last_success`
and `health().last_success_ms` retain only the last **clean analytics** result/time;
export, degraded reads and failures never replace it. Persist actual last-good
projections externally across process restarts. Missing data is never zero usage.

401/403 become `authentication`; other >=400 statuses become `upstream_http`;
redirect/non-200 success becomes `unexpected_http`. Error bodies and exception
messages are discarded. Malformed envelopes abort the traversal; malformed records
are skipped with a count and degraded state, never raw-payload logging/quarantine.

## Returned fields and normalization

Records preserve event hash, native request ID when present, event timestamp,
export ingestion timestamp, provider, model/requested/resolved/response models,
failed flag, CPAMP status code, latency and TTFT. Missing fields remain null. Imported
and legacy rows can have empty method/path; neither is used to infer identity.

Only explicit token/metadata allowlists survive. Tokens: input, output, reasoning,
cached, cache_read, cache_creation, total, and export's legacy cache_tokens. Numeric
integers are preserved; unsafe/noninteger values become null and inconsistent,
never guessed zero. Missing fields stay absent. Metadata: auth_index, api_key_hash,
source_hash, session_id, parent_session_id, executor_type, reasoning_effort,
service_tier, stream, generate, header_trace_id, cache_input_mode and
derived_cache_input_mode. Strings are bounded/control-character checked. These
are internal facts, not permission to export them wholesale to Langfuse.

Raw prompts/output, keys, account snapshots, access-token hashes, client IP,
forwarded-for, user agent, endpoint/path text, fail summaries, arbitrary nested
metadata, and raw_json are discarded. Metadata keys cannot smuggle nested objects.
Source is `cpamp.analytics` or `cpamp.export`, with `cpamp_version=v1.14.9`.
**Raw here means that HTTP surface's numeric values, not original CPA queue JSON.**

For proven Codex subset semantics, projection version is
`cpamp-1.14.9/codex-subset-v1`. Required counts must all be present, nonnegative
signed-64-bit integers (booleans are not counts):

1. Analytics input is normalized total input; cached is residual cache. Derived
   read = cache_read + cached.
2. Export input/cache fields are legacy stored values. Derived read = cache_read +
   max(max(cached, cache_tokens) - cache_read - cache_creation, 0).
3. Exclusive buckets: input_uncached = input - derived read - cache_creation;
   cache_read = derived read; cache_write = cache_creation;
   output_nonreasoning = output - reasoning; reasoning = reasoning.
4. All buckets must be nonnegative and sum exactly to returned total. Input
   100/read 20/output 40/reasoning 10 yields **80/20/0/30/10**, total **140**.
5. Quality is `derived`, never original CPA `complete`. Unsupported provider/mode
   or missing counts → `unknown`; invalid counts, contradictory provider/cache
   hints or totals → `inconsistent`. In either case buckets/normalized total are
   null. CPAMP may synthesize total = input + output + reasoning; such subset
   disagreement stays visible instead of being silently corrected.

HTTP cannot expose original CPA accounting quality and may already have substituted
missing numeric fields. Even internally consistent zeros only prove surfaced CPAMP
zeros, not a measured provider zero. Both surfaces omit SQLite row ID, execution ID,
queue trace ID, original queue raw JSON/canonical breakdown, stored normalized
columns and per-record cost. Analytics also omits created_at_ms. Every record carries
`known_omissions`; none of these are invented from timestamps, cursors or request IDs.

Cost is `amount=None`, `currency=None`, `classification="unknown"`, no pricing
version. No per-record price source was queried. Future pricing must explicitly
label calculated cost estimated; CPAMP aggregate cost is not an exact row cost.

## Bounds and reproducibility

Defaults: 500 rows/page (upstream max 50,000), 100 pages, 50,000 encountered rows,
4 MiB/page/status body, 64 MiB/export, 64 KiB/JSONL line, 10-second HTTP operation
timeouts and 120-second whole-traversal deadline. Counts include rejected/duplicate
rows. Declared and streamed sizes are checked. Configurable positive bounds never
silently truncate; exceeding a bound returns unavailable/incomplete. Narrow windows
for large reads. In-memory results/dedup and last-good result are bounded, not a
scalable durable rebuild store. No checkpoints or automatic retries are implied.

Reproduce using Python 3.12 with the repository's locked dependencies:

```bash
gh release download v1.14.9 --repo seakee/CPA-Manager-Plus \
  --pattern cpa-manager-plus_v1.14.9_linux_amd64.tar.gz --dir /path/to/artifacts
PYTHONPATH=src python scripts/cpamp-read-poc.py \
  --release-archive /path/to/artifacts/cpa-manager-plus_v1.14.9_linux_amd64.tar.gz \
  --output /path/to/adapter-results.json
python -m pytest tests/test_cpamp.py
```

The POC verifies the archive checksum/version, starts a fresh loopback-only binary
with isolated environment/config/data, imports synthetic fixtures, invokes the
production adapter, restarts it, and archives/verifies/deletes only its new scratch
rows to exercise real retention warnings. It terminates its process and removes its
scratch directory. Its setup HTTP writes are confined to that harness, never exposed
by the adapter. Linux amd64 binary required. Synthetic IDs/metadata only; no external
CPA, provider/OAuth or live collection. Parent #1/#3 tenant-correlated usage gate
remains open despite successful durable-history HTTP validation.
