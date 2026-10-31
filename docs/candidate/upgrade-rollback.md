# #6 isolated upgrade and rollback rehearsal

**Prepared October 31, 2026 — execution pending D5/D6 approval; no rehearsal has
run.** This plan closes the evidence gap identified in the [#6 readiness
matrix](readiness.md) without modifying the live candidate, shared CPA/CPAMP
services, Langfuse, ingress or production state.

The existing same-pin populated restore remains the baseline evidence. It used
LiteLLM **1.106.6**, PostgreSQL **17.11**, 98 table fingerprints, 213 migrations and
a provider-disconnected callback-disabled configuration. It is not cross-version
upgrade or rollback evidence.

## Approval boundary

Execution must wait for the following readiness-register decisions:

- **D5:** exact target LiteLLM and PostgreSQL versions, image digests and source
  artifacts.
- **D6:** rollback authority, stop conditions, evidence owner and treatment of
  work created after the pre-upgrade checkpoint.

D1–D4 should also be recorded before treating the rehearsal as production evidence:
custody, retention, protected backup/retrieval and external CPA/CPAMP/Langfuse
recovery boundaries. A rehearsal can be technically run on private local artifacts
before those production decisions, but it cannot close criterion 1 or authorize
cutover.

Until D5/D6 are complete, do not substitute a moving “latest” tag or an operator
preference for the target version. Do not run a target image against the live
`proxylens-candidate` volume.

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
| LiteLLM version | `1.106.6` | **D5 required** |
| LiteLLM image digest | `sha256:c09a77d998058dd78835a45a985eae747d257f2b183db06852fba536f3d1113c` | **D5 required** |
| PostgreSQL version | `17.11` | **D5 required** |
| PostgreSQL image digest | `sha256:0b81cec82228160abfa753aeaad0609b709eb26eeb950f2e404ad2326e1cc370` | **D5 required** |
| LiteLLM source/OCI revision | `61c6ab78393ef45683dd7d963d2a315bd845e20b` | **D5 required** |
| Schema/migration expectation | 213 / `20261009000000_add_credential_display_name` | **target evidence required** |
| Rehearsal ID | — | **operator assigns** |
| D5/D6 approval references | — | **required before execution** |

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
- capture a baseline custom dump and schema-only dump for rollback;
- capture migration count/latest name and image/config checksums;
- verify the clone has no default route, no provider credential and no shared
  external network.

Start the baseline binary only after pre-start equality passes. Readiness and native
readback are control observations; login/session and heartbeat writes must be
recorded separately from the pre-start equality result.

### 3. Run baseline readback without inference

Using private fixture credentials through a local client, verify and record:

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
2. Keep the clone database available and retain its pre-upgrade dump.
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

The target clone must pass all applicable checks before rollback is attempted:

| Area | Required observation |
|---|---|
| Process/DB | Readiness passes; target image/version and database version match D5; no unhandled migration errors. |
| Schema | Schema/migration change is expected, reproducible and recorded; no unexplained loss or drift in selected native tables. |
| Native identity | A/B login, role, premium flag, own user/history/aggregate reads and key ownership remain correct. |
| Native facts | Checkpoint request IDs, owners, statuses, usage, cost and totals remain readable; later activity stays separately identified. |
| Authorization | Cross-user aggregate remains denied; cross-user history does not disclose rows. |
| Controls | Key/model limits and model discovery remain readable; no new key or policy is created by the rehearsal. |
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
baseline/
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
