# Operations and recovery

The worker owns the scheduled projection, completion scan, Langfuse outbox
delivery/recovery, retention participants, and Keycloak group reconciliation.
The API installs the proof-gated usage routes against the same PostgreSQL
projection. All of these are diagnostic or rebuildable paths; CPAMP remains the
sole CLIProxyAPI usage-queue consumer and the authoritative durable history.
Do not enable tenant usage without both independently reviewed live proof files.

## Ownership and data lifetimes

| Data | Default | Owner / behavior |
| --- | --- | --- |
| Request lineage and gateway request state | 90 days | ProxyLens; request acceptance/start time |
| Usage projection | 90 days | ProxyLens; original CPAMP event time, not import time |
| Local Langfuse outbox | 90 days | ProxyLens; original request time, not retry/enqueue time |
| Audit/security events | 365 days | Separate `resource_audit`; event time |
| Remote Langfuse observations | 90 days | Dedicated project; operator API cleanup plus blob lifecycle |
| Applications, keys, policies, orphan references | Explicit lifecycle | Never deleted by usage cleanup |
| Provider credentials/config | CLIProxyAPI | Never deleted or rotated by usage cleanup |
| Identity/groups and CPAMP durable history | Keycloak / CPAMP | No ProxyLens automatic upstream deletion |

Raw prompt/output capture remains disabled. Audit and health output use fixed
action/state fields and counts, never HTTP bodies, arbitrary upstream metadata,
exception strings, tokens, authorization URLs, OAuth state or credentials.

`RetentionPolicy.from_environment(mapping)` accepts positive whole days through
these names. They govern local cleanup. Remote Langfuse retention is a separately
reviewed operator lifecycle and is not configured as a ProxyLens local cutoff:

```text
PROXYLENS_RETENTION_REQUEST_DAYS=90
PROXYLENS_RETENTION_PROJECTION_DAYS=90
PROXYLENS_RETENTION_OUTBOX_DAYS=90
PROXYLENS_RETENTION_AUDIT_DAYS=365
```

### Exact local cutoff and transaction contract

Compute one aware UTC clock per run. Delete only timestamps **strictly less than**
`run_time - days * 24 hours`; equality survives. A naive clock or nonpositive day
count is rejected. No calendar/DST rounding. Config changes cannot lower a
committed request/projection/outbox retention floor and resurrect previously
pruned data. Increasing retention preserves more future data; recovering already
pruned history is a separate deliberate restore, not normal source replay.

`RetentionRunner` requires the three typed participants `outbox`, `projection`,
`gateway`, and runs them in that order in **one PostgreSQL transaction**. It:

1. Takes exclusive advisory transaction lock `706769006`; advances durable floors.
2. Locks known lineage/hold tables against concurrent modification.
3. Runs each participant's local prune hook; remote I/O and commits are forbidden.
4. Prunes expired unheld ingress/native bindings and old unreferenced source
   identity rows. `lineage_usage_event.first_seen_at` is a conservative local
   identity-record clock; it does **not** replace CPAMP source-time admission.
5. Deletes expired audits, then appends `retention.delete` with counts and cutoffs.
   Audit failure rolls back deletion, participant work and floor updates together.

Writers call `retention_cutoffs(connection, policy, now=...)` **before row locks**.
Its shared advisory lock lasts through commit. Import rejects original event times
older than `cutoffs.projection`; exporters reject request starts older than the
request/outbox floors. Missing/invalid source time is quarantined, not replaced by
the current time. This prevents source reimport or restored cursors from recreating
expired local records. The integrated projection and exporter writers use this
helper before their row-lock work.

Each participant maintains `operations_retention_hold(participant, reference,
request_id)` transactionally with dependent work. Holds have no automatic timeout:
pending/dead-letter/uncertain work cannot disappear merely because lineage ages.
The outbox participant must first expire old work with a visible counted outcome,
then release holds when safe; younger pending work keeps its parent. Active/unknown
gateway work and surviving projections also hold parents. A database FK error
causes rollback rather than dangling references.

Native-ID collisions receive special treatment: if any request in a connected
collision component survives, **all** its ownership evidence survives. Removing an
old conflicting owner must never turn `ambiguous` into ownership by the remaining
group. This can extend metadata retention; monitor oldest holds/collisions and
resolve through explicit operations, never automatic reassignment.

The initial implementation is single-host, transaction-bounded cleanup. It can
hold locks across a large sweep; do not bypass statement/lock limits to force it.
Measure backlog before enabling large histories; chunking requires the same
atomic floor/hold/collision contract and additional concurrency validation.

## Health and dependency outages

`operations_health(...)` consumes existing probes, `CPAMPAdapter.health()` /
`read_status()`, and typed projection/export snapshots. It performs no HTTP itself.
The worker's `/health/ready` endpoint combines bounded PostgreSQL, CPAMP,
Keycloak-authority and CLIProxyAPI probes with this redacted operations snapshot.
It reports six distinct components: PostgreSQL, Keycloak, CLIProxyAPI, CPAMP,
projection, Langfuse. Internal URLs, reason strings and arbitrary error text are
discarded. Langfuse health does not gate gateway forwarding.

| Failure | Required response / recovery |
| --- | --- |
| PostgreSQL | Fail closed before forwarding if resource authorization, audit or ingress cannot commit. No cached permit/unrecorded model request. Uncertain post-dispatch outcomes remain explicit; never replay provider requests to repair telemetry. |
| Keycloak | New login and management fail closed. Existing locally validated tokens follow `docs/identity.md`'s bounded JWKS policy; cached verification does not prove current group existence. Missing group becomes orphaned only after authoritative not-found, never on timeout. |
| CLIProxyAPI | Forwarding unavailable; no automatic model POST retry, including pre-response ambiguity. CPA restart can lose in-memory usage events. |
| CPAMP/read adapter | Preserve last valid projection; `stale`, `degraded` or initial `unavailable`, never fabricated zero usage. A successful collector poll does not prove durable-history completeness. |
| Langfuse | Provider response remains independent; backlog/uncertain/dead-letter state visible. Disabled exporter is `disabled`, not successful delivery. Remote acceptance is not confirmed query visibility. |

Projection becomes stale at **age >= 60 seconds** or adapter failure; a reported
source gap remains degraded even after a successful recent poll. Unknown counts
remain null. Worker readiness requires authenticated CPAMP collector status. When
the live proof gate permits history polling, it also requires the read adapter;
otherwise CPAMP `history_state` and projection state explicitly report `disabled`,
with no invented history-success timestamp. An intentionally disabled history
reader must not prevent first startup. Collector failures still fail readiness.
Projection freshness and Langfuse delivery remain diagnostic and do not gate
provider forwarding. Gateway readiness depends on PostgreSQL, Keycloak and CPA,
not remote observation delivery. Health is diagnostic and never substitutes for
per-request authorization, group validation or durable lineage.

CPAMP status supplies collector state, last-consumed/last-inserted timestamps and
dead-letter count. Its current status contract does not prove queue completeness:
health explicitly emits `queue_coverage: unknown`. Display source coverage/loss
from the supported read adapter when available; preserve unknown when absent.
**Never call a CPA usage queue endpoint, including from health or recovery.**
CPA's bounded in-memory queue cannot recover events already expired or lost at
restart. Do not promise replay without an actual supported CPAMP durable record.

### Orphans, audit and restart

Resource reconciliation uses stable Keycloak group IDs. Confirmed missing groups
leave their applications/keys visible to authorized operators and unusable.
Recreating the same display name cannot repair them. Explicit administrator repair
creates a replacement application, revokes old keys and audits old/new references;
historical lineage keeps the original group. See `docs/resources.md`.

Lifecycle mutation/audit are atomic. Denials must be redacted and durably recorded
where storage is available. Retention appends its audit in the deletion transaction.
Final integration must add safe integration/export/reconciliation transitions to
the same audit boundary; sink HTTP acknowledgement and DB commit cannot be made
one distributed transaction. A crash after possible remote acceptance becomes
`uncertain`, not an automatic resend. Restart resumes projection/outbox work only;
it never resubmits inference.

## Backup tooling: private, matching recovery sets

Use Python 3.12 with `requirements-dev.lock` installed using `--require-hashes`.
`scripts/recovery.py` provides `backup-postgres`, `restore-postgres`,
`backup-foundation`, `restore-foundation`, and `validate`. Run `--help` for inputs.

- Supply credentials only through an owner-only JSON connection file outside the
  checkout (`host`, `port`, `dbname`, `user`, `password`, optional SSL settings).
  Populate it using a private editor/secret manager. Never put values into shell
  commands, URLs, history, Git, GitHub, logs or `set -x` output.
- Passwords reach PostgreSQL subprocesses through their private environment, not
  argv. Local host administrators can still inspect process state. Container
  utility forwarding passes environment **names**, not values, to the engine.
- Every archive/manifest/report is 0600 under a new 0700 directory. Existing
  directories, symlink paths and populated database/volume targets are refused.
  A failed run leaves its partial new destination for private diagnosis; use a
  fresh name on retry. No global prune, overwrite or automatic failed-target drop.
- A recovery set includes exact Git commit, immutable image references/IDs,
  dependency locks, Compose configuration, matching secrets and environment, all
  stores, SHA-256 file manifest, and a nonsecret common recovery-set label. A dirty
  checkout is recorded in a logical backup and is not a release recovery pin.
- Checksums detect damage, not maliciously replaced archives; authenticate/encrypt
  the entire private set before off-host storage. Restore only trusted sets.
  Apply a separate backup lifetime and test off-host decryption/recovery.

### Logical PostgreSQL backup and populated restore drill

This captures one consistent exported PostgreSQL snapshot. `pg_dump` and private
per-table row fingerprints read the **same snapshot**. It does not capture roles,
tablespaces, other databases, or other services. Provision the matching role and
extensions first; use the cold matching set for full-stack recovery.

```sh
umask 077
python scripts/recovery.py backup-postgres \
  --connection-file /secure/ops/proxylens-db.json \
  --destination /secure/backups/new-postgres-set \
  --recovery-set deployment-snapshot-001
python scripts/recovery.py validate /secure/backups/new-postgres-set
python scripts/recovery.py restore-postgres \
  --connection-file /secure/ops/recovery-admin.json \
  --backup /secure/backups/new-postgres-set \
  --database proxylens_restore_001 \
  --destination /secure/recovery/new-validation-report
```

The admin connection points at an existing maintenance DB; **the restore database
must not exist** and must differ from source/maintenance/template names. Restore
creates it using `template0`, then `pg_restore --single-transaction --exit-on-error`
without owner/ACL recreation. All schema-table row counts and content fingerprints
must match before success is reported. Partial failure never touches source DB.
Use a dedicated recovery role/server, because trusted SQL archives execute SQL.

Use matching-major `pg_dump`/`pg_restore` on PATH. Alternatively add
`--pg-container <same-server-container> --engine docker` (or `podman`) to both
commands; the script verifies cluster system identifier and client/server major
before use. This option requires permission to read `pg_control_system()`. It is
not a way to restore into some other container silently. Pin patch versions for a
release rehearsal; local automated tests can use a dedicated PostgreSQL 17 utility
container and record its actual version. The October 27 isolated acceptance drill
uses the reference PostgreSQL 17.11 image, separate from shared test instances.

### Quiesced foundation backup

Use the commands below in place of the manual archive loop in `docs/deployment.md`.
They support a local Linux engine with visible volume mount paths. Source volumes
must already exist. Stop restart supervisors for the maintenance window so no
writer can restart between the script's before/after checks.

1. Close ingress; wait for active requests. Stop API/gateway/worker.
2. Let CPAMP drain while CPA still runs. Inspect supported CPAMP status/history;
   absence of completeness evidence stays unknown. Record any loss interval.
3. Stop CPAMP, CPA and Keycloak, then both PostgreSQL servers. Never copy live
   PostgreSQL files or only the main file of live SQLite/WAL storage.
4. Prepare a private `images.json` mapping component names to actual immutable
   `repository@sha256:...` or `sha256:...` IDs, including application builds and
   Keycloak's custom mapper image. Preserve those image artifacts off-host.
   Make a private environment-file copy (0600); keep the secrets directory 0700.
5. Invoke the backup. It checks stopped source-volume consumers, reads source
   volumes through read-only host binds (avoids named-volume copy-up), archives
   whole volumes with numeric ownership, and verifies safe archive paths/hashes.

```sh
python scripts/recovery.py backup-foundation \
  --project proxylens --confirm-quiesced \
  --secrets-directory /secure/deployment/secrets \
  --environment-file /secure/ops/environment \
  --images-file /secure/ops/images.json \
  --destination /secure/backups/new-foundation-set \
  --recovery-set deployment-snapshot-001
python scripts/recovery.py validate /secure/backups/new-foundation-set
```

Five volumes: ProxyLens PostgreSQL, Keycloak PostgreSQL, CPA config, CPA OAuth
directory, CPAMP data including SQLite sidecars/archives. **Matching CPAMP data key
is essential** to read encrypted configuration. Copying a changed secret file does
not rotate credentials already persisted in any store. Preserve matching runtime
secrets; do not run a new secret initializer over the restored set.

### Cold restore and startup validation

Restore into a new project on an isolated host/internal network, with ingress and
provider egress closed. Choose unused volume names/host ports; keep original stores
stopped and untouched. The script verifies manifest, rejects unsafe tar members,
creates only new labeled volumes and refuses nonempty targets before extraction.

```sh
python scripts/recovery.py restore-foundation \
  --backup /secure/backups/new-foundation-set \
  --project proxylens-recovery-001 \
  --destination /secure/recovery/new-foundation-files
```

Services are not started automatically. Verify the recorded checkout, helper image,
app image IDs and dependency pins. Recreate the recorded environment privately
with new project/ports and restored secret mounts; extracted files stay under the
0700 destination. PostgreSQL physical copies require compatible major/platform.
For an intentional cross-major migration, use the supported PostgreSQL upgrade
procedure and a separate rehearsal.

Validate in this order:

1. Offline: PostgreSQL `pg_controldata` reports clean shutdown; restored CPAMP
   SQLite integrity and foreign-key checks pass without ignoring nonempty WAL.
   Check CPA config and credential directory. Do not print row/credential data.
2. Start both databases; verify schema/migrations and nonloopback authenticated
   access (loopback `trust` cannot prove password recovery).
3. Start Keycloak and CPA with matching versions; verify existing realm/client
   secrets, issuer/JWKS, stable group IDs, preserved config and provider validity.
   A restored OAuth file does not guarantee the provider has not revoked it.
4. Start CPAMP as the only collector; verify matching data-key decryption,
   durable history counts/bounds and supported collector status. No manual queue
   pop. Explain unavailable/expired source intervals rather than guessing joins.
5. Start ProxyLens with ingress still closed. Verify keys/policies, audit, ingress,
   native collisions, projection bounds/cursors and uncertain outbox state. Apply
   retention floors before any restored replay/export scan. Missing groups remain
   orphaned; no same-name reassignment.
6. Restore/validate external Langfuse below. Reconcile accepted/uncertain
   observations read-only before considering explicit retry; remote state may be
   ahead of the snapshot. Open ingress only after dependency checks succeed.

### Enabled external Langfuse stores

Coordinate a matching set with its operator, using **the pinned deployed version**.
For v4.69.0, include PostgreSQL project/config data, ClickHouse observation stores,
Redis queue persistence (AOF/RDB as configured), and object buckets/raw-event/media/
export data plus lifecycle policies. Preserve project keys, salt/encryption keys,
storage credentials, worker/web image digests and configuration privately.

Pause ProxyLens export; stop ingress to Langfuse; drain/record outstanding jobs;
stop Langfuse workers/web before cold storage copies. Restore storage and credentials
first, start migrations/web/worker in the deployment's supported order, then verify
project identity, authenticated v2 readback, backlog and a new synthetic metadata
span. Same-ID re-ingestion is not a supported update/exactly-once recovery method.
The five-volume foundation script does not back up this external deployment.

## Remote 90-day Langfuse retention: OSS runbook

Use a dedicated project and **one ProxyLens request per trace**. Self-hosted built-in
project retention is Enterprise-only; setting `LANGFUSE_INIT_PROJECT_RETENTION=90`
does not enable it on OSS and does not update an existing project. The following
is an operator-owned recurring job contract, not an implemented/verified scheduler.
No command in this tranche deletes remote data.

Hourly, in UTC:

1. Freeze cutoff = current UTC minus 90 days. Prevent old local exports/source
   reimport first. Retention is based on original request/observation start time.
2. Read `GET /api/public/v2/observations` with `fields=core`, `limit=100`, a fixed
   `fromStartTime` project-history lower bound and `toStartTime=cutoff`; follow
   `meta.cursor` using identical bounds. Locally filter **startTime < cutoff** so
   endpoint bound inclusivity cannot delete exact-cutoff rows. Traverse older
   windows even if an intermediate window is empty.
3. Deduplicate `traceId`; verify all observations in that trace belong to the same
   expired request. Trace deletion removes every observation/score in that trace,
   not just rows in the filter interval. Skip mixed/uncertain traces and alarm.
4. Persist an owner-only deletion manifest/checkpoint. Submit project-authenticated
   `DELETE /api/public/traces` with JSON `{"traceIds":[...]}`, at most 1000 IDs per
   call. Read keys from secret files inside the job, never command-line Basic auth.
5. HTTP acceptance means scheduled deletion. Re-query v2 observations to verify
   query-visible disappearance, retain pending receipts, and alert on stuck work.
   Ensure the trace-delete consumer is enabled and the project is not in the
   deployment's deletion skip list. Limit deletion batches/retries; do not replay
   model requests or send replacement observations.
6. Repeat overlapping/full historical expiration sweeps, including after restore.
   A monotonically advanced cursor alone misses delayed ingestion of old events.

Separately set **90-day object-creation-age expiration** on the dedicated raw-event
bucket/prefix, including noncurrent versions and delete markers if versioned.
Apply explicit media/export/backup lifetimes too. In pinned v4.69.0, raw OTLP blobs
are not all registered in the blob-deletion log: successful trace deletion does
not prove those objects disappeared. Verify bucket permissions and actual expired
object removal. Observation time and object-creation time are different clocks;
delayed ingestion plus asynchronous lifecycle means this is not a strict physical
90-days-from-request bound. A stricter bound needs a shorter object TTL and maximum
export age whose sum fits the window, including measured lifecycle delay.

Project retention/deletion does not imply deletion of saved dataset copies,
independent exports, backups or audit logs. Keep capture disabled and define the
scope of remote deletion evidence explicitly.

Pinned contract evidence: scratch `langfuse.md` references v4.69.0 commit
`a0ef9519ce6c934f7db929251a17c35f4080f3c2`, public v2 observation read, trace deletion
route/worker and raw-blob logging gap. Official references rechecked 2026-10-26:
Langfuse administration data-retention/data-deletion and self-hosting blob-storage
documentation; PostgreSQL 17 `pg_dump`; GitHub Actions PostgreSQL service containers.
Scratch `langfuse-live.md` proves ingestion/readback and same-ID duplicate risk,
**not remote retention**. A disposable remote deletion/lifecycle drill remains open.

## Upgrade, rollback and validation status

Before upgrade, freeze and back up the complete matching set. Rehearse exact
versions on isolated restored stores; verify Keycloak custom mapper compatibility,
CPA/CPAMP trace/read contracts, PostgreSQL migrations/checksums and Langfuse v4
ingestion/deletion behavior. Upgrade storage only when required by its supported
path, then Keycloak, CPA/CPAMP as a tested pair, ProxyLens, and independently
Langfuse. Recheck tenant usage proof gates and metadata redaction before ingress.

Rollback stops new writers and restores the entire old matching set into fresh
targets with old code/images/secrets. Do not run old binaries on migrated schemas
without explicit upstream downgrade support. Record writes lost after snapshot,
remote observations still ahead of local state, and source history no longer
replayable. Never use `compose down -v` or engine-wide prune as a rollback step.

CI uses hash-locked dependencies, Ruff lint/format, Compose config and all pytest
tests against freshly created real PostgreSQL databases. **Any skipped test fails
CI.** The recovery test seeds resources/key/policy/audit/lineage, restores into a
new database, compares fingerprints, verifies key authorization and lineage through
repositories, and rejects a second restore to the existing target.
The final-schema recovery case also populates projection records/checkpoints and
an in-flight outbox attempt. Restore preserves those facts; an expired lease becomes
`UNCERTAIN` and cannot be claimed for resend. A simulated CPAMP outage preserves
restored records/last-success time, and replay after recovery does not duplicate
them. This is synthetic source evidence, not provider recovery.

Evidence boundaries:

- Earlier foundation cold restore succeeded on five isolated cloned volumes,
  matching secrets, pinned services and private network; source stores untouched.
  It had empty ProxyLens schema/CPAMP history/OAuth directory. It is real foundation
  recovery evidence, not final populated Phase-1 recovery.
- This tranche exercises populated PostgreSQL resources and lineage, exact local
  retention, audit rollback and filesystem safety. Final full-stack recovery,
  provider reauthorization and remote retention remain separate acceptance gates.
- The runtime hooks are integrated and validated by the locked application suite;
  live provider correlation/history proof and full-stack recovery remain open gates.
