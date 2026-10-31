# #6 isolated upgrade and rollback rehearsal

**October 31, 2026 — bounded isolated upgrade and fresh-database rollback passed.**
The [results below](#observed-results-october-31-2026) and
[sanitized evidence](evidence/2026-10-31-upgrade-rollback.json) record both attempts.
The [#6 readiness matrix](readiness.md) retains the separate production gates.

The existing same-pin populated restore remains the baseline evidence. It used
LiteLLM **1.106.6**, PostgreSQL **17.11**, 98 table fingerprints, 213 migrations and
a provider-disconnected callback-disabled configuration. It is not cross-version
upgrade or rollback evidence.

## Approval boundary

The owner approved the isolated D5/D6 rehearsal in this conversation on October 31,
2026 (recorded at `2026-10-31T03:05:45.771942Z`), delegated suitable pinned LiteLLM
target selection/verification and evidence custody to the OpenCode agent, required
PostgreSQL 17.11, and authorized stopping on any documented failure. The exact
instruction is retained in private `approval.json` under
`/data/tmp/opencode/proxylens-litellm-20261029/issue6-upgrade-rollback-20261031`.
This is rehearsal authority only. Live-service changes, provider inference, queue
reads, external telemetry mutations and production cutover remain unauthorized.

D1–D4 should also be recorded before treating the rehearsal as production evidence:
custody, retention, protected backup/retrieval and external CPA/CPAMP/Langfuse
recovery boundaries. A rehearsal can be technically run on private local artifacts
before those production decisions, but it cannot close criterion 1 or authorize
cutover.

D5 selection: `v1.108.0-rc.1`, a **prerelease for isolated rehearsal only**. The
official release list still identifies 1.106.6 as the latest stable release. The
selected RC's notes describe parity with the v1.106.x patch fixes; tag commit and
registry OCI revision match. Installed package version is `1.108.0` (the image tag
retains `-rc.1`); both installed Prisma schemas match pinned source. Its seven added
PostgreSQL migrations are additive; the 213 baseline migration files are unchanged.
No target promotion or production suitability is inferred from these checks.

Private verification retains the official release/ref responses, registry index,
amd64 manifest/config, installed schema/migration files and pinned-source comparison.
Image signature verification was not performed. Source URLs are retained in the
verification manifest; no moving tag is used for execution.

## Non-negotiable safety invariants

Every attempt gets a new private recovery directory, Compose project, database
cluster, volume and loopback port. The following are stop conditions, not warnings:

1. Any command targets the live `proxylens-candidate` project, its volume, the
   existing ingress or a shared service.
2. The source candidate is stopped, recreated, or pointed at a migrated database.
3. A target clone has a default route, shared CPA/Langfuse network, real CPA
   credential, CPAMP credential, or management credential.
4. A provider request, inference replay, CPAMP queue read, telemetry replay, or
   external Langfuse mutation occurs.
5. A migration error, unexplained schema drift, missing owner/history/key fact,
   unexpected credential exposure, or failed pre-start fingerprint comparison is
   observed.
6. Rollback is attempted by downgrading a binary against a migrated database.

The rehearsal uses the standalone offline restore topology: one internal network,
no default route, dummy CPA endpoint `127.0.0.1:9`, no real provider credential and
no Langfuse overlay. Synthetic telemetry, if selected for the target check, goes to
a local isolated receiver only and contains no real credentials or private content.

## Target declaration

Complete this table in the private rehearsal manifest after D5. Do not place
credentials or private trace payloads in the repository.

| Field | Baseline | Approved target |
|---|---|---|
| LiteLLM version | `1.106.6` | Tag `v1.108.0-rc.1`; installed package `1.108.0` |
| LiteLLM image digest | `sha256:c09a77d998058dd78835a45a985eae747d257f2b183db06852fba536f3d1113c` | `sha256:eee5c577573756a46c3a41177cd742e06a05a50feb0acc1520cad4fcf6ad6b8f` (linux/amd64) |
| PostgreSQL version | `17.11` | `17.11` |
| PostgreSQL image digest | `sha256:0b81cec82228160abfa753aeaad0609b709eb26eeb950f2e404ad2326e1cc370` | Same baseline digest |
| LiteLLM source/OCI revision | `61c6ab78393ef45683dd7d963d2a315bd845e20b` | `7a3c6229e1f41146d8dc8f543fd07f664c6a9707` |
| Schema/migration expectation | 213 / `20261009000000_add_credential_display_name` | 220 / `20261015000000_managed_object_end_user_id`; schema SHA256 `873f78ae1d36e62145d5d67933146e63b80991fd2f000c21bfa32ffa68b17ac0` |
| Rehearsal ID | — | `issue6-upgrade-rollback-20261031` |
| D5/D6 approval references | — | Owner instruction recorded above and private `approval.json` |

If PostgreSQL changes major version, use a dump/restore or the separately approved
PostgreSQL major-upgrade method. Do not mount a PostgreSQL data directory created by
one major version into another and call the result a rollback. For the first
rehearsal, keep LiteLLM and PostgreSQL changes separate when possible so a failure
has one attributable cause.

## Rehearsal phases

### 1. Freeze and verify the matching recovery set

Start from the retained populated recovery set at
`/data/tmp/opencode/proxylens-litellm-20261029/issue6-populated-recovery-20261030`
or a newly approved equivalent. Verify its private permissions and checksums before
copying it into a new rehearsal directory. Preserve the original set unchanged.

Record, privately:

- baseline dump, 98 table fingerprints and pre-start equality result;
- baseline LiteLLM/PostgreSQL versions, image IDs/digests, schema hash and migration
  count/latest name;
- active and offline config checksums, secret-loader checksum and secret-set
  identity without printing values;
- checkpoint rows, owners, statuses, token/cost facts and later-accounting interval;
- source/shared container start times and the fact that the live candidate was not
  touched.

Use the [matching restore procedure](recovery.md#reproduce-the-isolated-restore) for
the dump and pre-start fingerprint checks. The restore project must be new and
provider-disconnected.

### 2. Establish the baseline clone

Create a private copy of the standalone restore Compose file. Use a new project
name and volume, retain the pinned baseline images, and keep the callback-disabled
offline configuration. Before starting LiteLLM:

- restore the dump into a new PostgreSQL cluster;
- compare all table fingerprints to the source set;
- retain the restored input dump and capture a schema-only baseline;
- capture migration count/latest name and image/config checksums;
- verify the clone has no default route, no provider credential and no shared
  external network.

Start the baseline binary only after pre-start equality passes. Readiness and native
readback are control observations; login/session and heartbeat writes must be
recorded separately from the pre-start equality result.

### 3. Run baseline readback without inference

Using private fixture credentials through a local client, verify and record. If
the archived UI session has expired, use the session returned by a fresh native
login on the clone without rewriting the archived fixture:

1. A/B native login, `internal_user` role and `premium_user=false`.
2. A/B own user, history and aggregate reads.
3. A/A2/B key ownership, alias, model allowlist, 10 RPM / 20,000 TPM limits,
   null monetary budget and null expiry.
4. Local `/v1/models` discovery as an authenticated read, not inference.
5. A cross-user aggregate denial and the native no-disclosure history result.
6. Request IDs, owners, status, token fields, costs and checkpoint totals, keeping
   later source activity as a separate accounting interval.

Do not call the fixture provisioning command, create replacement keys, or submit a
provider request to make a readback succeed.

### 4. Apply the approved target on the clone

Create a **private** target Compose copy. Change only the approved target references
and any target-required configuration explicitly listed in D5. Keep the baseline
Compose, config, secrets and pre-upgrade dump immutable beside the target copy.

#### LiteLLM-only target change

1. Stop only the baseline clone's LiteLLM container.
2. Keep the clone database available. With the clone app stopped, capture the
   immutable pre-upgrade dump and fingerprints from the same unchanged DB state;
   verify a warning-free dump and record login/heartbeat differences from input.
3. Start the approved target LiteLLM image against that clone database.
4. Capture startup output privately, migration count/latest name, schema-only dump,
   image identity and effective config checksums.

#### PostgreSQL target change

1. Keep the baseline PostgreSQL cluster and volume untouched.
2. Create a new target PostgreSQL cluster/volume using the approved target image.
3. Restore the pre-upgrade custom dump into the target cluster using the approved
   compatible utility path.
4. Run the approved target LiteLLM binary against the target cluster.
5. Record whether the PostgreSQL change was same-major dump/restore or a separately
   approved major-version procedure.

Do not combine a PostgreSQL data-directory replacement with an application upgrade
without recording the separate boundaries and rollback set.

### 5. Verify target behavior and migration

Record the upgrade outcome independently of rollback. A failed target check stops
the upgrade; after preserving evidence, new-database rollback may still be exercised
under D6. Rollback success cannot turn a failed upgrade into a pass.

| Area | Required observation |
|---|---|
| Process/DB | Readiness passes; target image/version and database version match D5; no unhandled migration errors. |
| Schema | Schema/migration change is expected, reproducible and recorded; no unexplained loss or drift in selected native tables. |
| Native identity | A/B login, role, premium flag, own user/history/aggregate reads and key ownership remain correct. |
| Native facts | Checkpoint request IDs, owners, statuses, usage, cost and totals remain readable; later activity stays separately identified. |
| Authorization | Cross-user aggregate remains denied; cross-user history does not disclose rows. |
| Controls | Personal-key/model limits and model discovery remain readable; no personal key or policy is provisioned. Native login may create UI-session rows on the clone. |
| Telemetry | Run the selected target-version synthetic native callback/transport check with local isolated capture, or record the check as blocked with the reason. Verify trusted owner/session mapping and targeted masking using synthetic markers only. |
| Isolation | No provider dispatch, queue read, external sink mutation, shared-service restart or live-candidate change. |

The telemetry row is not satisfied by a callback-disabled restore alone. If target
telemetry cannot be exercised safely in the clone, leave criterion 3 partial and
record the missing evidence rather than attaching the shared Langfuse service.

### 6. Roll back from the pre-upgrade set

Rollback must use a **new** rollback database/volume and the exact baseline binary,
config, schema/artifacts and secrets captured before the target started:

1. Stop only the target clone.
2. Retain its target logs, migration output, schema dump and readback artifacts.
3. Create a new rollback project and PostgreSQL cluster.
4. Restore the immutable pre-upgrade dump; require zero restore warnings and exact
   pre-start table-fingerprint equality.
5. Start the baseline LiteLLM image only after equality passes.
6. Repeat readiness, native identity, owner/history/key/model and authorization
   checks from phases 2–3.
7. Compare the rollback facts to the baseline, allowing only documented login,
   heartbeat and other startup writes.

Do not downgrade the target binary in place. If any work was admitted after the
pre-upgrade checkpoint, stop admission and record it as a separate accounting
interval; never replay it to repair history or telemetry.

### 7. Preserve and classify evidence

The private rehearsal directory should contain at least:

```text
manifest.json
approval.json
input/
  postgres.dump
baseline/
  preupgrade.dump
  preupgrade-fingerprint.jsonl
  image-and-config-checksums.txt
schema.sql
  migrations.txt
  fingerprint.jsonl
  readback.json
target/
  image-and-config-checksums.txt
  schema.sql
  migrations.txt
  migration-output.txt
  readback.json
  telemetry.json
rollback/
  schema.sql
  migrations.txt
  fingerprint.jsonl
  readback.json
  comparison.json
network-isolation.json
SHA256SUMS
```

Sanitize any committed evidence. Keep dumps, secrets, fixture credentials, raw
headers, cookies, prompts/source code, outputs, tool payloads and trace bodies
private. The manifest must state the target references, operator, UTC timestamps,
approval references, source recovery-set identity, observed changes and limitations.

## Pass/fail decision

Criterion 3 can change from **Partial** only when D5 and D6 are complete and both
the approved target upgrade and pre-upgrade-snapshot rollback pass the required
checks. A same-pin restart, a target-container startup, a schema-only comparison or
an in-place binary downgrade is insufficient.

Record one of:

- `passed_bounded_upgrade_and_rollback` — all required checks pass and limitations
  are listed;
- `blocked` — an owner decision, target artifact or required check is missing;
- `failed` — a required check fails; preserve the clone and evidence for diagnosis;
- `inconclusive` — the environment or evidence is insufficient; do not infer pass.

This rehearsal does not authorize production traffic, cutover, key issuance,
external-store mutation, queue access, telemetry replay or service retirement.

## Observed results: October 31, 2026

**Outcome: `passed_bounded_upgrade_and_rollback`.** PostgreSQL remained at its
17.11 digest throughout. The forward target was `v1.108.0-rc.1`, not a new
production selection. The candidate configuration, CI pin and live runtime remain
1.106.6. Native provider/client checks were excluded by the owner's instruction;
the result is limited to migration, restored facts/access and synthetic telemetry.

| Check | Observed result |
|---|---|
| Retained input | 23 original checksum entries verified; 98 tables / 272 rows matched before baseline startup; 12 spend logs retained. |
| Forward upgrade | Readiness passed; 213 → 220 completed migrations, all applied checksums match installed files. Four empty tables and three columns added as expected; no baseline migration changed/removed. |
| Native state | A/B login as ordinary `internal_user`, `premium_user=false`; A has 10 history rows (3 checkpoint + 7 later), B has 2. IDs, owners, statuses, usage/cost/timing, existing aggregate values and user policy preserved. |
| Keys/access | A/A2/B key metadata and model discovery return 200; owners, 10 RPM/20,000 TPM, budgets, expiry and spend preserved. Both cross-owner aggregate checks return 403; history filters return 200 with zero foreign rows. |
| Usage | Native history/aggregate APIs and `/ui/usage/` HTML return 200. Interactive browser workflow was not repeated. |
| Synthetic telemetry | All six existing native callback tests pass in the target image with `--network none`, synthetic loopback capture and no real credentials. Attribution, masking, visible tools/content and native dispatch covered; no external Langfuse readback. |
| Fresh-database rollback | Exact baseline image/config/secrets plus pre-upgrade dump in a new volume: 98 fingerprints equal before startup, zero restore warnings, 213 migrations, baseline schema restored, all baseline native checks pass. |
| Side effects | Zero provider submissions, queue reads, inference replay, external telemetry mutations or live-service changes. All 44 pre-existing container identities/start times/status/restart counts unchanged; all 63 retained source files unchanged. |

### First stop and comparator correction

Attempt 1 (`03:12:08Z–03:14:39Z`) stopped the target after A's aggregate comparison
failed. The recorded response preserved every baseline metric but added
`total_ptu_hours: 0.0`. Pinned source
`litellm/types/proxy/management_endpoints/common_daily_activity.py:DailySpendMetadata`
at `7a3c6229` defines this additive field. Whole-dictionary equality was therefore a
rehearsal-comparator defect, not observed accounting loss. The stopped attempt and
its successful new-database rollback remain preserved.

The corrected comparator requires every baseline field/value and exactly that
source-verified addition. Captured-response checks confirm it still rejects changed
token totals, missing spend and undeclared additions. Attempt 2
(`03:17:20Z–03:19:18Z`) used new projects/volumes and repeated baseline restore,
upgrade and rollback successfully. No upstream/runtime code or fixture was patched.

### Snapshot and evidence boundaries

Baseline startup removed one stale worker-heartbeat row and its A/B logins created
two UI-session rows: 272 → 273 total rows. The clone app was then stopped before
the immutable pre-upgrade dump/fingerprints were captured. Rollback matched those
273 rows before startup. Each later pair of native logins adds two UI-session
rows; original A/A2/B personal keys and retained request facts remain intact.
Fresh login keys were used because the original 24-hour UI sessions had expired;
the private fixture file was not edited. JWT decoding here extracts the native
session for the local test client, not a replacement authorization mechanism.

The target has 102 table fingerprints. Of the 98 existing tables, only migration
history and UI-session rows changed after upgrade; the remaining fingerprints
matched. The rollback database schema SHA256 is the baseline
`8a3580cbe04c5a5c2df78eb8b339917438fd10c82aa99c9c925d7465f94ffe66`;
the upgraded schema SHA256 is
`9c23097c0fad685376c47671d8ffdc03a611c7ebeb5bc39f99316509dc2bd156`.

Evidence directories, relative to `/data/tmp/opencode/proxylens-litellm-20261029/`:

- `issue6-upgrade-rollback-20261031/`: approval, upstream/registry verification,
  initial stopped attempt, first rollback, synthetic telemetry, original/final
  service metadata and source-integrity inventory.
- `issue6-upgrade-rollback-20261031-attempt2/`: corrected one-off runner, captured
  comparator checks, independent baseline/target/rollback artifacts and comparisons.

Both directories are private (0700/0600) with manifests and SHA256SUMS; nine
rehearsal containers are stopped, four DB volumes and both evidence sets retained.
The one-off scripts/Compose copies stay with private evidence; they are not a new
recovery framework. The original set's SHA256SUMS was 0664 inside a 0700 directory
and did not cover the dump/fingerprint files. Its 23 listed hashes passed; new
copies use 0600 and record hashes for all files, with dump integrity additionally
checked by restored fingerprint equality. The original set was not rewritten.

Limits: image signatures not verified; no production target promotion, live ingress
rollback, actual-client/provider protocol test, external-store recovery, off-host
retrieval, PITR, or durable-telemetry guarantee. The unmodified synthetic test
passes the baseline server-version label to one preparation helper, while importing
and exercising the target image's runtime. No broader A1–A6 acceptance is implied.
