# Candidate recovery and production-readiness preparation

**October 29, 2026 — partial #6 evidence; no production approval or cutover.**
Uses the [candidate deployment](deployment.md), [shared contract](../specs/litellm-poc.md)
and proposed [ADR 0002](../adr/0002-litellm-personal-usage.md). This rehearsal restored
existing native account/key/policy state, not provider request history. Deployed
#7 acceptance has not started. The owner subsequently accepted native client
retries; the [local preflight's former blocker classification is superseded](decisions.md#local-client-preflight-reclassification).
A1–A6 and owner candidate acceptance remain pending. Leave #6 open.

The owner subsequently approved **native Langfuse content-rich tracing**: prompts
(including source code), model output, gateway-visible tool arguments/results,
useful errors and metrics. Native integration/configuration comes first; selective
credential masking and verified user/session attribution remain required. The
earlier blanket metadata-only/filter-adapter objective is superseded. **Actual
runtime at this rehearsal still has no callback**, message/prompt capture off and
error-detail persistence off. This work neither activates telemetry nor proves
delivery. Trace-project access, actual content retention and recovery ownership
must be recorded for the selected #8 setup, then approved for production; do not
derive them from the earlier metadata-only assumption.

## State, secrets and recovery owners

Owners below are operational responsibilities for this POC. The production owner
must assign custodians, access, storage locations, backup cadence/expiry and
recovery objectives before production; these are not implicitly approved defaults.

| Selected state / secret | Backup and retention responsibility | Current recovery boundary |
|---|---|---|
| Native PostgreSQL `litellm` DB, `proxylens-candidate_candidate_db` | Candidate operator / #6; production retention owner approves policy | Whole logical DB: users/password hashes, key hashes/owners/blocked/expiry fields, limits, spend/budget counters/windows, invitations, config overrides, history/aggregates, migrations. Populated account restore below. |
| `postgres_password` | Candidate operator / #6, matched private secret set | Same password file used by restored DB and app; DB role recreated by pinned PostgreSQL entrypoint. No independent cluster-role backup needed for this dedicated single-role POC. Revisit if roles/extensions/tablespaces change. |
| `master_key`, `salt_key`, `ui_password` | Candidate operator / #6, matched private secret set | Preserve bytes with DB: admin access, encryption and session/key dependencies must not be regenerated on restore. No lost-secret recovery or rotation was tested. |
| A/A2/B plaintext keys and A/B passwords in private `fixture.json` | POC operator; production users/credential custodian own issued credentials | DB backup preserves verifiers, not rediscoverable plaintext personal keys. Private fixture enables the rehearsal; it is test material, not a production credential-distribution design. |
| CPA inference `cpa_api_key`, route/network | CPA resource owner issues/rotates service credential; candidate operator backs up its matching copy | Archived privately, **not mounted in restore app**. No CPA management key in candidate. Restore uses dummy credential and loopback discard endpoint. |
| CPA OAuth/auth/config and provider execution state | Existing authorized CPA operator | External service shared with other fixtures; not included in native DB dump. No stop, global backup, restore, rotation or recovery evidence in this tranche. |
| Optional CPAMP DB/history/encryption/admin key | Existing CPAMP operator | Existing sole CPA queue consumer; not a candidate personal accounting dependency. External recovery/retention verification pending if selected. |
| Langfuse project/API keys, memberships/access; service PostgreSQL, ClickHouse, object storage, Redis/queues and service encryption/auth secrets | #8 / trace-project operator owns project access/content retention; external Langfuse operator owns coordinated service recovery; #6 assembles evidence | No callback/project recovery exercised here. Old shared fixtures are not candidate evidence. Content-rich trace retention/deletion and backup copies need actual settings and ownership; no assumed 90-day policy. |
| Exact image IDs/digests, schema/migrations, Compose/config/secret loader, price map | Candidate operator / #2/#6 | Preserve matching source/artifacts and secret set beside dump; mirror/save image blobs before upgrade if registry availability is required for recovery. This rehearsal used locally cached pinned images, not an air-gapped image-import test. |
| In-memory request/rate counters and pending native writes | Candidate operator records limits; #7 verifies selected behavior | No Redis selected. Volatile state is not in `pg_dump`; do not claim uninterrupted limits or lossless accounting. |
| Container/journal logs and private backup/evidence files | Host operator / #6 | Podman reports `journald`, no Compose rotation override (`Size=-1B`). Host journal expiry not verified. This local 0700/0600 rehearsal set has no scheduled expiry/off-host encrypted copy; production custody and expiry remain pending. |
| Old ADR 0001 ingress, Keycloak/group data, custom DB, CPA/CPAMP state and secrets | Existing-runtime operator | Preserve existing recovery sets and group-history semantics through separately approved cutover. Candidate dump does not replace their backups. |

## Actual native retention and persistence settings

Checked installed **LiteLLM 1.106.6** source, live mounted config/environment,
`GET /config/list?config_type=general_settings`, and native DB on October 29.
No retention mutation or cleanup was executed. Database `LiteLLM_Config` had only
`auto_router_tuning_baseline_v3`; `LiteLLM_ConfigOverrides` was empty. The live API
reported spend/health/tag retention as `null`, source `unset`.

| Item | Actual selection / pinned default |
|---|---|
| Spend details and derived tool index | `maximum_spend_logs_retention_period` **unset / None**. No scheduled age deletion. This is unbounded until explicitly changed, not a durability guarantee. |
| Auto-router session/user-session/daily rollups, health-check rows, daily tag spend | `maximum_autorouter_session_retention_period`, `maximum_health_check_retention_period`, `maximum_daily_tag_spend_retention_period` all **unset / None**; their cleanup disabled. Features may have no rows. |
| Cleanup schedule, if a retention period is later selected | `maximum_spend_logs_retention_interval` defaults **`1d` plus random 0–60 seconds**. Optional cron takes precedence. No cleanup job is selected with all four periods unset. |
| Cleanup work bounds, currently inactive | **1,000 rows/batch**, **500 batches/table/run**, **300 seconds/run**, **30 seconds/batch timeout**; partitioning off. These are processing bounds, not retention horizons. |
| Daily user/team/global usage, users, personal-key records, budget state | No age-expiry job selected for these records. Spend-detail cleanup is not a blanket retention policy for all tables; native budget resets are not history deletion. |
| Personal A/A2/B credential expiration | `expires=NULL`; no automatic expiry override. User/key `max_budget`, `budget_duration`, `budget_reset_at` NULL; `spend=0`. 10 RPM/20,000 TPM on each user and personal key. |
| UI session keys | Native duration **24h**; each login's key `max_budget=1.0` (USD session allowance), `spend=0` in fixture. Distinct from personal-key policy. `LITELLM_EXPIRED_UI_SESSION_KEY_CLEANUP_ENABLED=false`; optional cleanup defaults 86,400-second interval / 1,000 keys, but is disabled. Expiration is not row deletion. |
| Content / errors at snapshot | `disable_spend_logs=false`, `store_prompts_in_spend_logs=false`, `turn_off_message_logging=true`, `disable_error_logs=true`. Current metadata storage configuration only; approved content-rich telemetry objective above is not yet deployed. |
| Native DB batching / budget reset scheduler | `PROXY_BATCH_WRITE_AT=10` seconds; budget rescheduler bounds **597–605 seconds**. Timing defaults, not a measured loss/freshness/strict-budget guarantee. |

Pinned source anchors (relative to installed `litellm/`, also source commit
`61c6ab78393ef45683dd7d963d2a315bd845e20b`): `_types.py` is
`proxy/_types.py:3158–3200`; `proxy/proxy_server.py:11184–11233` schedules cleanup;
`proxy/db/db_transaction_queue/spend_log_cleanup.py:497–621,724–809` identifies
pruned tables; `constants.py:1755–1760,1790,1809–1816,1844,1876–1877` sets defaults;
`__init__.py:460–467` and `proxy/auth/login_utils.py:424–438` set UI-session budgets.
Installed source copies are in the private recovery set.

Official reference: `https://docs.litellm.ai/docs/proxy/spend_logs_deletion`.
Live documentation already mentions a startup-cleanup option absent from the
inspected pinned scheduler; do not substitute moving docs for installed behavior.
The old **90/365/90-day proposals are not candidate defaults or approved policy**.
Production decisions must cover native metadata, content-rich traces, access,
external stores, operational logs and retained backup copies separately.

## Matching recovery set

The exercised set uses the exact [#2 pins](deployment.md#pins-and-source-verification):

- LiteLLM amd64 manifest `sha256:c09a77d998058dd78835a45a985eae747d257f2b183db06852fba536f3d1113c`, package `1.106.6`.
- PostgreSQL amd64 manifest `sha256:0b81cec82228160abfa753aeaad0609b709eb26eeb950f2e404ad2326e1cc370`, server/client **17.11**.
- Prisma schema SHA256 `1ed6fbff070ed7cdf2fa86f667d7b6eedd6a0be2d7036250a54cfe360de183db`; **213** completed migrations, latest `20261009000000_add_credential_display_name`.
- Config, `secret_env.py`, both Compose files, matching secrets and private fixture;
  source commit `ef2057f`. The restore Compose file is added by this tranche.

The live LiteLLM container reports the image-index digest
`sha256:37e2dafb088a7723beb998590682957386dfc83ffea1848486f8e0e5cfac0b06`;
both it and the selected amd64 manifest resolve to image ID
`9ab6d30d9c82cea5338c03a3bf5f607fbee4b9b078da14028a7267ade026e088` locally.
Verify architecture and image ID as well as digest type rather than declaring a
mismatch from index-vs-platform digest text alone.

`scripts/recovery.py` remains **existing-runtime tooling**: its PostgreSQL package
requires root Compose/old Python lockfiles; foundation backup names old volumes.
Neither pins candidate binary/config/schema or its selected state set. Do not use
its foundation command with the candidate project. No new recovery framework is
needed here: use `pg_dump`, `pg_restore`, and native APIs.

## Reproduce the isolated restore

Run from repository root with Bash, Podman 5.7.0 / Compose 5.6.1 and the already
running dedicated candidate. Commands below target only a **new** private backup
directory and **new** restore project. The source is never stopped. PostgreSQL
online snapshots cover committed DB state, not pending LiteLLM in-memory writes
or external CPA/Langfuse state. For a future populated run, coordinate admission
drain/write settling and #7 before a common cutover checkpoint; do not stop the
shared candidate independently.

### 1. Capture matching artifacts and a consistent snapshot

```sh
set -euo pipefail
umask 077
export PRIVATE=/data/tmp/opencode/proxylens-litellm-20261029/private
export RECOVERY_DIR=/data/tmp/opencode/proxylens-litellm-20261029/recovery-new
export SOURCE_DB=proxylens-candidate-postgres-1
export COMPOSE=/data/tmp/opencode/docker-compose-v5.6.1
export DOCKER_HOST=unix:///data/tmp/opencode/proxylens-litellm-20261029/podman.sock
mkdir -m 700 "$RECOVERY_DIR"  # must fail if it exists
mkdir -m 700 "$RECOVERY_DIR/artifacts"
cp -R "$PRIVATE/secrets" "$RECOVERY_DIR/secrets"
cp "$PRIVATE/fixture.json" "$RECOVERY_DIR/fixture.json"  # POC readback only
cp "$PRIVATE/candidate.env" "$RECOVERY_DIR/source.env"
cp deploy/candidate/{compose.yaml,restore.compose.yaml,config.yaml,secret_env.py} \
  "$RECOVERY_DIR/artifacts/"
find "$RECOVERY_DIR" -type d -exec chmod 700 {} +
find "$RECOVERY_DIR" -type f -exec chmod 600 {} +
git rev-parse HEAD > "$RECOVERY_DIR/source-commit.txt"
podman exec "$SOURCE_DB" pg_dump --version
podman exec "$SOURCE_DB" psql -X -U litellm -d litellm -Atc 'SHOW server_version'
podman exec proxylens-candidate-litellm-1 cat \
  /app/.venv/lib/python3.13/site-packages/litellm/proxy/schema.prisma \
  > "$RECOVERY_DIR/artifacts/schema.prisma"
cat > "$RECOVERY_DIR/fingerprint.sql" <<'SQL'
SET TIME ZONE 'UTC';
SELECT format('SELECT json_build_object(''table'', %L, ''rows'', count(*), ''md5'', md5(coalesce(string_agg(row_to_json(t)::text, E''\n'' ORDER BY row_to_json(t)::text COLLATE "C"),''''))) FROM public.%I t;', tablename, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY tablename
\gexec
SQL
```

Compare archived config/loader with `/candidate/config.yaml` and
`/candidate/secret_env.py` in the running app; verify installed package/image/schema
against the matching set above. If #8/config/secrets changed, capture and review
the new set and revise the offline configuration before restoring it. The supplied
restore Compose is tested only with the no-callback #2 configuration.

For fingerprints tied to the dump, open terminal A (same `SOURCE_DB`):

```sh
podman exec -it "$SOURCE_DB" psql -X -qAt -v ON_ERROR_STOP=1 -U litellm -d litellm
```

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET TIME ZONE 'UTC';
SELECT pg_export_snapshot();
```

Leave this session open. In terminal B (same exports), paste that nonsecret ID:

```sh
SNAPSHOT='<exported-snapshot-id>'
podman exec "$SOURCE_DB" pg_dump -U litellm -d litellm \
  --format=custom --no-owner --no-acl --lock-wait-timeout=5s \
  --snapshot="$SNAPSHOT" > "$RECOVERY_DIR/postgres.dump" \
  2> "$RECOVERY_DIR/dump.stderr"
test ! -s "$RECOVERY_DIR/dump.stderr"  # inspect any warning privately
```

While A's transaction remains open, import its snapshot into B's read-only
fingerprint session. The actual rehearsal streamed fingerprints from the original
exporter transaction; importing the same snapshot gives the same rows. This writes
only a host-side private result, not files in the source container. The sorted
JSON MD5 is a small-fixture equality check, not an authenticity proof or a scalable
large-history hashing scheme.

```sh
{
  printf '%s\n' 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;'
  printf "SET TRANSACTION SNAPSHOT '%s';\n" "$SNAPSHOT"
  cat "$RECOVERY_DIR/fingerprint.sql"
  printf '%s\n' 'COMMIT;'
} | podman exec -i "$SOURCE_DB" psql -X -qAt -v ON_ERROR_STOP=1 -U litellm -d litellm \
  > "$RECOVERY_DIR/fingerprint-source.jsonl"
```

Now `COMMIT;` and `\q` in terminal A. Keep fingerprints private: even hashes can
identify sensitive state. Create private checksums (the actual set instead uses
`manifest.json`), and verify before restoring:

```sh
(
  cd "$RECOVERY_DIR"
  find artifacts secrets -type f -print0 > checksum-files.nul
  printf '%s\0' postgres.dump fixture.json source.env source-commit.txt \
    fingerprint.sql fingerprint-source.jsonl >> checksum-files.nul
  sort -z checksum-files.nul | xargs -0 sha256sum > SHA256SUMS
  sha256sum --check --status SHA256SUMS
)
```

Do not put credentials, raw rows or DB archives in Git. Before a later restore,
repeat the checksum verification from inside the recovery directory.

### 2. Start a fresh, provider-disconnected database

`deploy/candidate/restore.compose.yaml` is a **standalone file**, not an overlay
for the live candidate. It uses one internal network, no CPA/Langfuse connection,
no DB port, no real provider credential, dummy CPA URL `127.0.0.1:9`, no telemetry,
and loopback app port 14006. Only matching DB/master/salt/UI secrets are mounted.

```sh
export RESTORE_PROJECT=proxylens-candidate-restore-new
export RESTORE_PORT=14006  # choose an unused loopback port
# Confirm this project, its containers and ${RESTORE_PROJECT}_restore_db are absent.
podman ps -a --format '{{.Names}}'
podman volume ls --format '{{.Name}}'
"$COMPOSE" -p "$RESTORE_PROJECT" -f "$RECOVERY_DIR/artifacts/restore.compose.yaml" \
  config --quiet
"$COMPOSE" -p "$RESTORE_PROJECT" -f "$RECOVERY_DIR/artifacts/restore.compose.yaml" \
  up -d --wait --wait-timeout 90 postgres
export TARGET_DB="${RESTORE_PROJECT}-postgres-1"
podman exec "$TARGET_DB" pg_restore --version  # must match the selected 17.11 pin
# Target entrypoint creates only postgres. No IF NOT EXISTS / DROP / --clean.
podman exec "$TARGET_DB" createdb -U litellm --template=template0 litellm
podman exec -i "$TARGET_DB" pg_restore -U litellm -d litellm \
  --single-transaction --exit-on-error --no-owner --no-acl \
  < "$RECOVERY_DIR/postgres.dump" 2> "$RECOVERY_DIR/restore.stderr"
test ! -s "$RECOVERY_DIR/restore.stderr"
podman exec -i "$TARGET_DB" psql -X -qAt -v ON_ERROR_STOP=1 -U litellm -d litellm \
  < "$RECOVERY_DIR/fingerprint.sql" > "$RECOVERY_DIR/fingerprint-restored.jsonl"
cmp "$RECOVERY_DIR/fingerprint-source.jsonl" "$RECOVERY_DIR/fingerprint-restored.jsonl"
# Equality must pass BEFORE starting the app.
```

Keep a failed target isolated for inspection; choose a new project for a retry.
The same DB name `litellm` is safe only because this is a separate cluster/volume;
the secret loader expects that name and service DNS `postgres`.

### 3. Start the matching binary and read native state

```sh
"$COMPOSE" -p "$RESTORE_PROJECT" -f "$RECOVERY_DIR/artifacts/restore.compose.yaml" \
  up -d --wait --wait-timeout 240 litellm
curl --fail "http://127.0.0.1:$RESTORE_PORT/health/readiness"
```

Verify installed schema hash and migration count/latest name again. Compare
`pg_dump --schema-only --no-owner --no-acl` before/after startup, excluding only
random `\restrict` / `\unrestrict` lines. The matching binary should not migrate
the selected snapshot. Login and heartbeats do legitimately change row contents
after startup; full-row equality belongs **before** startup.

Using private fixture credentials in a local HTTP client, never shell argv/logs:

1. `POST /v2/login` for A and B using `{username: email, password}`. Confirm
   returned native role `internal_user`, `premium_user=false`; use its session
   key for the following user reads. Decoding the native login JWT for this
   client is not replacement token validation or a new authorization boundary.
2. `GET /user/info?user_id=<own-id>`: verify own role, allowlist, RPM/TPM and
   budget/spend fields. `GET /spend/logs/v2?user_id=<own-id>&start_date=2026-10-29&end_date=2026-10-30`:
   verify availability and the expected snapshot history. In this run: empty.
3. For each original A/A2/B key, use it as bearer for `GET /key/info` (no secret
   in URL) and `GET /v1/models`; check owner/alias, model allowlist, 10 RPM/20,000
   TPM, null monetary budget/expiry and zero spend. Model listing is local
   authenticated readback, **not inference**.
4. Check restored original UI-session budget/expiry through native key info if
   still valid; this run also used master-authorized key lookup before expiry.
   New login creates new session rows; do not call the fixture provisioning
   command or recreate users/keys to make readback succeed.

The actual rehearsal made these calls via Python `urllib`, loading credentials
from files and retaining responses only privately. With #7's real retained sample
available, repeat snapshot/restore and compare request IDs, owner, numeric
usage/cost and totals through native APIs/UI. A live request on a restored deployment
requires separately authorized provider routing and a designated new test request;
never replay inference to repair missing usage/telemetry or reconstruct history.
Native client retries follow the [retry contract](../specs/litellm-poc.md#retry-boundaries).
No history or provider request was fabricated to complete this gate.

When finished, stop/remove **only the restore project** and retain its volume/set:

```sh
"$COMPOSE" -p "$RESTORE_PROJECT" -f "$RECOVERY_DIR/artifacts/restore.compose.yaml" down
# No -v. Never point this command at proxylens-candidate or the shared external stack.
```

PostgreSQL contracts used: `https://www.postgresql.org/docs/17/app-pgdump.html`
and `https://www.postgresql.org/docs/17/app-pgrestore.html` (online consistent
single-DB backup, exported snapshot, custom archive, transactional restore).

## Observed results and limits

Private set: `/data/tmp/opencode/proxylens-litellm-20261029/issue6-recovery-20261029`
(0700 directories/0600 files). Project `proxylens-candidate-restore`, port 14006;
separate volume `proxylens-candidate-restore_restore_db`.

- Online snapshot/custom dump **269,979 bytes**, no warnings; restore into a new
  cluster/DB with matching 17.11 client/server, no warnings.
- **98 tables / 232 rows**, every table count/sorted-row fingerprint identical
  before app startup. Populated: users **3**, key/session rows **12**, invitations
  **2**, config **1**, heartbeat **1**, migrations **213**.
- Native A/B login and own user/history reads **200**. Original A/A2/B keys passed
  authenticated key info and model listing, preserving explicit ownership,
  allowlist and configured limits. Original A/B UI-session allowances **1.0**,
  zero spend and original expiries survived; personal budgets remain NULL.
- **Zero** spend logs/daily-user rows; no dedicated BudgetTable/PolicyTable rows.
  Policy exists on native user/key rows. Restored existing zero/null budget state,
  not a funded/consumed/reset-budget scenario. Monetary policy is not selected.
- Installed schema hash unchanged; normalized DB schema equal after startup,
  SHA256 `1cd7bcab6059ce3aa17eaa1f7dd40f7399ca82bd17aab80831669c3bb93648da`.
- App attached only to an internal network; no IPv4 default route, real CPA key
  unmounted. No provider inference, shared service restart, original-secret change,
  retention deletion, or telemetry mutation. Source candidate start times unchanged
  and both containers healthy. Known private fixture/secret values absent from
  restore app logs.
- Restore containers/network removed after validation; volume and private set
  retained. This is same-pin recovery evidence, not an upgrade, PITR, off-host
  disaster recovery, encrypted-backup custody, external-store recovery or #7 pass.

## Upgrade, health and separately approved cutover

**Upgrade/rollback preparation:** retain pre-upgrade binary/config/schema/migration
state plus matching DB and secrets as one set. Rehearse any proposed target version
on a new isolated clone; compare migration history, native login/key/history and
selected #7 cases. No cross-version migration was tested here. Treat a changed
schema as incompatible with the old binary until proven otherwise; rollback is
old pinned binary + **pre-upgrade snapshot in a new DB**, not binary downgrade
against migrated state. Keep old source volume/ingress recoverable; post-checkpoint
requests require explicit handling as a separate accounting interval, not replay.

**Health is three separate observations:** `/health/readiness` confirmed app/DB
availability; own history API confirmed readable native history (empty here).
Neither implies inference readiness. Actual-client/provider readiness awaits
deployed #7 evidence under the clarified retry contract; accepted native client
retries are not a blocker requiring correction. Telemetry is **disabled/unverified**;
eventual sink readiness and delivery/content/attribution evidence belong to #8/A5. Reuse
#7 restart/optional-dependency evidence when available; no duplicate fault matrix.

**Production sequence, not authorization to execute:**

1. Complete A1–A6 (including deployed retry-boundary evidence, persisted request history,
   selected controls, native content-rich telemetry and access), #1 owner acceptance,
   and coordinated ADR/glossary/guidance adoption. Record accepted native batching,
   volatility, limit propagation, missing fields and delivery limitations. No strict
   no-overspend, lossless accounting or exactly-once claim follows from this restore.
2. Assign and approve backup/retention/content-access custodians and actual values
   across the inventory; select recovery objectives/cadence, protected off-host
   backup location and tested retrieval. Complete retained-history restore and
   required CPA/Langfuse external recovery evidence. Preserve old recovery material.
3. Issue **new personal keys** bound explicitly to native users, distribute through
   the selected private channel, and verify native login. Keep old group-owned
   history read-only under its original semantics; establish a new personal
   accounting epoch. Never infer old owners from creators/current memberships or
   add CPA attempt totals to client-request totals.
4. Obtain separate cutover approval/window. Coordinate ingress drain and pending
   native writes, take matching checkpoints, switch the selected ingress, then
   repeat essential actual-client/login/usage/telemetry checks. Retain old routing,
   services, keys and state for the approved rollback window; no mirror/replay traffic.
5. Roll back ingress on wrong owner/access, broken client/stream continuation,
   missing/unreadable native facts, or failed accepted trace behavior. Stop new
   candidate admission, preserve its evidence and accounting interval, restore
   old routing/old credentials or the approved matching recovery set. Operators
   must explicitly decide treatment of post-checkpoint work and key revocation.
   Retire old services only after successful approved cutover and rollback-window
   acceptance. No such approval, switch, retirement or issue closure occurred here.
