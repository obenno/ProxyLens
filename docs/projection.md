# CPAMP usage projection (#10)

## Status

The implementation is locally validated, with partial live provider/correlation
evidence recorded privately by the Phase 1 continuation harness. Both live proof
gates remain closed by default. Partial live evidence and synthetic tests do not
enable deployment.
CPAMP remains the history authority and sole usage-queue consumer. This module
calls only the existing version-pinned `CPAMPAdapter` read methods.

## Integration responsibilities

Gateway/coordinator owns API/worker configuration and lifespan integration:

1. Apply migrations before serving: lineage `003`, projection `010`, and resource
   `009` tables before usage queries. `Database.migrate()` currently discovers all
   SQL recursively. `apply_projection_migration(connection)` is also exposed for
   an explicit migration runner; it is repeatable and participates in the caller's
   transaction. The SQL view itself depends on lineage, not resources.
2. Construct `ProjectionSettings(cpamp_instance_id, cpa_instance_id, keycloak_issuer)`
   with stable deployed identifiers. Reusing a CPAMP instance ID for a different
   store/CPA pairing is rejected. `ProjectionRepository(Database(...), settings)`
   is shared by the API and worker through PostgreSQL, not process memory.
3. Load proof through `load_proof_gate(settings, artifact_paths,
   approved_sha256=reviewed_digests)`. Keep the default disabled until both live
   deployed proofs have been independently reviewed. See evidence requirements below.
4. API: call `install_projection_routes(app, repository, gate=gate)` once. Identity
   lifespan must install the real `app.state.identity`. No alternate principal
   dependency is provided. All routes use Keycloak authentication, READ capability,
   issuer and current token group scope; platform-admin permits all groups.
5. Worker: construct its dedicated `CPAMPAdapter` using the server-side manager
   secret, pinned CPAMP version and matching instance ID; enter
   `projection_worker_lifespan(repository, adapter, gate=gate)` inside the service
   lifespan. This helper owns adapter open/close and task cancellation. Alternatively
   own `async with adapter` and call `ProjectionWorker.run(stop_event)`.
6. Operations: call `repository.health()` for internal diagnostics. Wrap storage
   failures as dependency-unavailable. Schedule ordinary polling via the helper;
   invoke `poll_once(rebuild=True)` for retained-history reconciliation. Do not run
   diagnostic exports concurrently on the same adapter. Export attempts never
   replace projection rows.
7. Retention/backup owner (#6) coordinates lineage, projection and exporter cleanup.
   Projection pruning does not delete lineage collision evidence. Keep that evidence
   at least as long as any dependent projection/export work. Source-store retention
   is an independent operational setting.

`app.py`, `config.py` and Compose integration belong to the gateway/coordinator.
There are no new environment enable switches, live-proof fixtures, secrets or
provider OAuth data in this change.

## Proof artifact contract

Exactly two separately reviewed JSON files are required, kinds `correlation` and
`durable_history`. Each contains:

- `schema_version: 1`, `status: "passed"`, timezone-aware `verified_at`;
- `provenance: "live_deployment"`;
- `binding`: exact `dataclasses.asdict(settings.binding)` including deployed CPA
  and CPAMP instance IDs, issuer, release/source pins and correlation method;
- `scenarios`: all codes returned by `settings.required_scenarios(kind)`.

The caller supplies a trusted SHA-256 approval set separately from those files.
The loader checks bytes against that set and rejects changed, oversized, missing,
unreviewed, wrong-version/instance, partial, or synthetic artifacts. Hash checks
prove integrity of reviewed evidence, not that an arbitrary author's claims are
true. The deployment reviewer must verify actual binaries/instances and the
observed scenario evidence; approval cannot be derived from the candidate file.
No approved digests ship here. Changing deployed binaries/instance pairing requires
new evidence and matching source binding, not a boolean toggle.

`allow_synthetic=True` exists only as an explicit Python test seam. Tests generate
temporary artifacts/digests. Production configuration must never forward that flag.
The existing #3/#4 repository evidence is deliberately insufficient for this loader.
Source inspection, isolated CPAMP imports and configuration labels are not live
correlation/durable-collector proof.

## Refresh, reconciliation, crash behavior

Defaults: 30-second start-to-start polling target, 60-second stale threshold,
five-minute overlap, one-day fixed windows, hourly full retained-history
reconciliation, 90-day local retention. Settings are independently configurable.

Every traversal uses fixed `[from_ms, to_ms)` bounds, the adapter's two-part
keyset cursor and both success/failure events. The next incremental scan starts
at the last **committed window end minus overlap**, never at a row timestamp or
response-generation timestamp. No finite overlap proves historical completeness;
periodic reconciliation scans the whole locally retained interval for late imports.

Each window is read by the adapter, then persisted into a private PostgreSQL run.
All windows must finish before a single transaction promotes staged records,
updates lineage, prunes expired projection rows and advances the checkpoint.
Transport/auth/cursor/schema failures, rejected records, conflicting staged
identities, concurrent page counts and count mismatches abort publication.
Normalization unknowns and explicit retention gaps may publish known facts with
degraded health; they do not become invented zero tokens or complete coverage.

The worker holds a PostgreSQL advisory transaction lock per source. A second worker
does no HTTP work. Crash/cancellation releases the lock; the next run removes the
unpublished staging rows and rereads the last committed window. Promotion failure
rolls back records, lineage and checkpoint together. A failed refresh preserves the
last valid projection and marks it stale. No repair ever replays a provider request.

**Rebuild means staged reconciliation, not unconditional replacement.** Upserts are
keyed by `(cpamp_instance_id, event_hash)`; native request IDs may name multiple
attempts and are never dedup keys. Fresh build and incremental/reconciled build
agree for the same retained source history, ignoring processing/checkpoint counters.
Absence in an analytics traversal is not proof of deletion. Previously observed
rows missing from a scan stay visible and set `retained_source_absence`; full
reconciliation can clear it after the source again accounts for retained rows.
Upstream deletion/retention means a fresh reconstruction may be incomplete, which
is explicit rather than silently discarding the last usable local history.

`read_export()` has no verifiable footer/snapshot checkpoint at this pin. Therefore
`rebuild_from_export()` returns false, records uncertainty and **never stages or
replaces data**, even for valid JSONL EOF or a purported verification flag. A future
destructive rebuild needs a separately reviewed snapshot contract.

Local pruning deletes event timestamps **strictly older than** `now - retention`,
in UTC milliseconds. The exact cutoff survives; old source replays are excluded.
Pruning occurs with successful promotion; standalone outage cleanup belongs to #6.

## Facts, ownership and schema

| Relation | Contract |
|---|---|
| `projection_sources` | Immutable deployment binding, committed window end, last success/reconcile/attempt, retained coverage warnings and last-run duplicate count. |
| `projection_runs`, `projection_stage` | Private run identity and bounded-window facts; never tenant-readable. Crash leftovers are removed by the next locked run. |
| `projection_records` | PK source instance/event hash, timestamp and sanitized `facts` JSONB. FK to `lineage_usage_event`; no authoritative owner columns. |
| `projection_resolved` | Dynamic join through `lineage_event_resolution` and immutable ingress. Later native collisions immediately remove earlier group/application attribution. |

`facts` preserves source/version, CPAMP hash, valid native CPA UUID, surfaced numeric
`raw_tokens`, `normalized` (quality, exclusive buckets, total, reason, derivation
version), requested/resolved/response models, provider, failure/status, latency,
export ingestion timestamp if supplied, known omissions and `cost`. Safe returned
provider trace ID is retained separately under `native_ids.provider_trace_id`; it
is never a CPA join key. Account hashes, auth indices, source sessions, arbitrary
metadata, prompt/output and error content are not copied into projection facts.

Raw means **CPAMP HTTP surface**, not original CPA queue JSON. The adapter alone
normalizes; projection never repeats that calculation. Codex 100 input/20 cache,
40 output/10 reasoning yields exclusive `80/20/0/30/10`, total 140. Missing or
inconsistent counts retain unknown/null buckets. Cost fields remain null with
classification `unknown` at the pinned HTTP contract; no pricing source exists.
Future amounts must retain currency, pricing version and evidence-based
classification; never sum different currencies or manufacture authoritative cost.

The view distinguishes `correlated`, `partial`, `missing`, `ambiguous`; replay is
reported as `duplicate_count`, not a second countable row. Conflicting native
claims remain sticky in lineage. No timestamp/model/account/shared-key guesses.

Tenant reads join current resource group/application states for `orphaned`; missing
references fail conservatively. Historical ownership remains the ingress snapshot.
Explicit orphan repair creates a successor application and cannot transfer history.
Authorized historical reads remain possible; gateway/resource APIs block new use.

## API and completeness

GET routes:

- `/api/usage` and `/api/usage/totals`;
- `/api/groups/{group_id}/usage`;
- `/api/applications/{application_id}/usage`;
- `/api/usage/records/{event_hash}` (configured source instance).

List/totals support group/application filters, `[from_ms, to_ms)`, limit 1–200 and
nonnegative offset. Totals are computed across the authorized filter, not the page.
Each read uses a fresh database snapshot for page and totals. Out-of-scope groups
return 403; applications/record details conceal existence with 404. No proof or
initially absent projection returns 503, not an empty success. JWT failure is 401;
storage/identity dependency failure is 503. Responses set `Cache-Control: no-store`.

`observed_records` counts known authorized facts; it may be zero when none is
known. `observed_tokens` sums only when there is at least one record and every
record has known normalization, otherwise null. `total_records`, `total_tokens`
and `cost` remain null. `coverage` is `unknown` or `incomplete`, never falsely
`complete`; this adapter cannot certify no collection loss or a truly empty
source. Empty records + zero observed count are explicitly **unknown coverage**.

Internal health exposes last success, scanned window, reasons, duplicate count and
source coverage details. No source ingestion watermark exists, so it is null.
State is unavailable before a valid commit, stale on failure/60-second age/old
window end/expected native-bound request lag, degraded on retained data defects or
known gaps, otherwise available. Available describes the read pipeline, not
complete usage. Historical gap evidence survives clean incremental polls.
Tenant responses expose only state, last-success time, coverage and null watermark;
global source counts and detailed reasons stay internal.

## Exporter read contract (#8)

Use the same verified gate and deployment binding, then query **current**
`projection_resolved` immediately before finalizing an observation. Example internal
query (parameters are trusted server configuration/lineage, never caller headers):

```sql
SELECT p.event_hash, p.cpa_request_id, p.request_id, p.facts,
       p.group_id, p.application_id, p.subject, p.trace_id,
       p.generation_id, p.session_id
FROM projection_resolved p
WHERE p.cpamp_instance_id = %s
  AND p.cpa_instance_id = %s
  AND p.keycloak_issuer = %s
  AND p.request_id = %s
  AND p.correlation_status = 'correlated';
```

Also validate `projection_sources.binding` against the configured binding. Join
resource states if needed for orphan metadata, without modifying historical owner.
No row means unknown/pending, not zero. Multiple hashes mean multiple retained
attempts; sum only known mutually exclusive buckets and preserve their identities.
Use normalized fields, never sum raw overlapping token counters. Cost stays unknown.
Explicitly allowlist metadata; do not export the whole facts/view or raw tokens.
Do not retain an earlier resolved owner as proof after later collisions.

The outbox stores the source lineage tuple only for scanner-produced correlated
observations. Its claim and pre-send lease fence re-read `projection_resolved` using
that tuple and the original ingress request. If a late native-ID collision changes
the current status, the job becomes `UNCERTAIN/lineage_invalidated` and no stale
payload is sent.

Stable generation IDs come from lineage. The selected Langfuse immutable-span
contract requires one delayed finalized generation, not early usage plus replayed
enrichment. Gate-disabled operation may export gateway-only partial metadata;
projection replay must not cause new generations or provider requests.

## Validation

Use locked Python 3.12 dependencies and isolated PostgreSQL:

```sh
PROXYLENS_PROJECTION_TEST_DSN='<disposable DSN>' \
python -m pytest tests/test_projection.py tests/test_projection_routes.py
```

The tests create/drop unique schemas, apply production migrations and use real
transactions, concurrent connections, DB-trigger failure injection and restarted
repositories. External CPAMP/JWKS HTTP is simulated; JWT verification is real.
Coverage includes paired evidence gates, replay/keyset pagination, late arrivals,
corrections, retention gaps, missing versus empty, staged rebuild equivalence and
failures, collisions, restart, lifecycle cancellation, scopes, orphan repair and
global-count isolation. These are local implementation checks, not live gate proof.
