# #6 production-readiness matrix

**October 30, 2026 — readiness incomplete; production cutover is not authorized.**

This matrix maps the live [issue #6](https://github.com/obenno/ProxyLens/issues/6)
acceptance criteria to the evidence already recorded in the
[candidate recovery record](recovery.md), [#7 acceptance](acceptance.md), and
[native Langfuse record](langfuse.md). It is a readiness decision record, not a
cutover approval.

## Overall status

**NOT READY FOR PRODUCTION CUTOVER.** The candidate has bounded same-pin restore,
native state readback, separated health observations, and documented A1–A6
limitations. Production readiness still requires approved operational ownership,
external-store recovery, off-host backup/retrieval, upgrade/rollback evidence,
key issuance and migration decisions, and a separate cutover approval/window.

| #6 criterion | Status | Evidence and current decision | Required to close |
|---|---|---|---|
| 1. State/secret backup and retention ownership | **Partial — production decisions required** | The recovery inventory assigns POC responsibilities for the native DB, secrets, CPA, CPAMP, Langfuse, images, volatile state, logs and old runtime. Actual production custodians, retention values, expiry, protected off-host location and retrieval cadence are not approved. Native spend-detail retention is unset; Langfuse `retentionDays=null`; host-log expiry and off-host encrypted copies are unverified. | Name production custodians; approve metadata/content/log/backup retention and deletion values; select protected off-host storage and retrieval cadence; verify access and expiry. |
| 2. Populated restore and native readback | **Pass — bounded same-pin evidence** | The populated restore matched 98 table fingerprints before startup, preserved the pinned LiteLLM 1.106.6/PostgreSQL 17.11 schema state, recovered users, personal-key ownership, limits, history and checkpoint metrics, and passed A/B login plus native history/key/model readback. | Retain the evidence and repeat only if the selected production backup format, version or state set changes. This pass does not cover external CPA/Langfuse stores, off-host disaster recovery or a funded/reset budget scenario. |
| 3. Upgrade/rollback compatibility | **Partial — cross-version evidence absent** | The recovery record defines matching-state rollback using an old binary and pre-upgrade snapshot in a new DB. No cross-version migration, PITR or upgrade/rollback rehearsal has been performed. | Select the target version; rehearse upgrade on an isolated clone; compare schema/migrations and essential client/history/telemetry checks; test rollback from the pre-upgrade recovery set. |
| 4. Health separates inference, native history and telemetry | **Pass — bounded observation** | Readiness, native history readback and telemetry/inference behavior are recorded as separate observations. #7 also recorded one-dispatch sink-outage isolation and no telemetry-triggered inference replay. | Preserve the three-signal health/runbook contract. The CPAMP-unavailable inference case and durable telemetry across restart remain untested and are not production guarantees. |
| 5. Native behavior and limitations documented | **Pass — bounded contract** | ADR 0002, the POC contract, A1–A6 evidence and recovery record document ownership, accounting, retry, access, masking, retention and delivery semantics. | Keep the stated limits binding: no strict lossless, exactly-once, no-overspend, freshness, capacity or durable-telemetry guarantee without separately measured scope. |
| 6. Cutover, keys, history and rollback plan | **Partial — execution decisions required** | The recovery sequence defines new personal keys, old group-history preservation, a new accounting epoch, ingress drain/checkpoint, rollback triggers and old-state retention. Actual key distribution, cutover window, custodians, checkpoint procedure and post-checkpoint treatment are not approved. | Approve key issuance/distribution; define old-history access and epoch boundary; choose cutover window; assign operators; confirm rollback triggers, retention window and post-checkpoint accounting/key revocation. |
| 7. Approved cutover and post-cutover checks | **Not started — explicit approval gate** | No ingress switch, production request, provider replay, mirror traffic, service retirement or issue closure occurred. | Obtain explicit cutover approval; execute the approved window; repeat essential client/login/Usage/telemetry checks; retain rollback state; retire old services only after successful rollback-window acceptance. |

## Owner decision register — October 31, 2026

No production-owner approval is recorded for the fields below as of October 31,
2026. `PENDING` means unresolved; it is not an approval or a production default.
Complete the decision, owner, UTC date and evidence-reference fields before changing
any matrix status.

| ID | Closes | Decision required | Evidence required before closure | Owner decision | Decision owner | Approved UTC | Evidence / approval reference |
|---|---|---|---|---|---|---|---|
| D1 | Criterion 1 | Name custodians for native DB/history, secrets, logs, images, old runtime state, CPA, CPAMP and Langfuse. | Signed custody map with server-side access boundaries and backup/recovery operators. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D2 | Criterion 1 | Set retention/deletion for native metadata/history, content-rich Langfuse traces, logs, backup copies and private recovery evidence; record secret rotation/expiry. | Approved retention table plus verified effective settings for each selected store. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D3 | Criterion 1 | Select protected off-host backup storage, encryption/key custody, backup cadence, expiry, retrieval cadence, RPO and RTO. | Successful retrieval/decryption rehearsal from the selected off-host location, with timestamps and sanitized checksums. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D4 | Criteria 1, 3 | Decide whether CPA, CPAMP and Langfuse external state are production dependencies; assign recovery scope and owners. | External-store inventory, backup/retrieval result or an explicit accepted non-dependency boundary for each service. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D5 | Criterion 3 | Select the target LiteLLM/PostgreSQL versions and image digests for upgrade rehearsal. | Isolated-clone upgrade evidence: migration history/schema comparison, native login/key/history/Usage checks, selected telemetry check and retained pre-upgrade snapshot. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D6 | Criteria 3, 6 | Approve rollback authority and triggers; require old binary plus pre-upgrade snapshot in a new DB rather than binary downgrade against migrated state. | Isolated rollback rehearsal with preserved evidence and explicit treatment of work created after the pre-upgrade checkpoint. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D7 | Criterion 6 | Approve new personal-key issuance, private distribution channel, old group-history access, accounting-epoch boundary and post-checkpoint accounting treatment. | Issuance ledger without secret values, native owner/readback checks, old-history access decision and epoch/checkpoint record. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D8 | Criteria 6, 7 | Select cutover window and timezone; name ingress, database, CPA, Langfuse, validation and rollback operators; set rollback-window retention and key-revocation authority. | Signed run sheet with checkpoint, drain, switch, validation, rollback and retirement steps. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |
| D9 | Criterion 7 | Explicitly authorize or reject production cutover after D1–D8 and the required rehearsals close. | Dated approval in the issue/decision record naming the approved window, scope, rollback authority and stop conditions. | **PENDING** | **PENDING** | **PENDING** | **PENDING** |

### Decision-entry form

Use this block for each decision register row. Do not put credentials, personal
keys, cookies, prompt/source content or private trace payloads in the repository or
issue comments.

```text
Decision ID:
Decision:
Approved value/scope:
Decision owner:
Execution/evidence owner:
Approval date and timezone (UTC):
Review or expiry date (UTC):
Evidence reference:
Rollback/stop condition, if applicable:
Notes and accepted limitations:
```

### Closure mapping

| Matrix criterion | Minimum recorded closure |
|---|---|
| 1. Ownership and retention | D1–D4 completed, approved retention/custody values recorded, and protected off-host retrieval evidence retained. |
| 3. Upgrade/rollback | D5–D6 completed and the selected-version isolated upgrade plus pre-upgrade-snapshot rollback rehearsal passes the required native checks. |
| 6. Cutover preparation | D7–D8 completed with key/history/epoch treatment, operators, window, rollback triggers and post-checkpoint handling recorded. |
| 7. Approved cutover | D9 completed before ingress change; post-cutover checks and rollback-window outcome are recorded afterward. |

The existing same-pin populated restore remains evidence for criterion 2. It does
not satisfy D3, D4, D5, D6 or D9: it used a provider-disconnected callback-disabled
configuration, performed zero provider calls and queue reads, and did not recover or
mutate external CPA/Langfuse state.

## Production blockers and owners

| Blocker | Evidence owner / decision owner | Current state |
|---|---|---|
| Native DB, secret, log and backup retention | #6 production owner with candidate/host operators | Inventory exists; production values, custodians and protected off-host retrieval are unapproved. |
| Langfuse project access, content retention/deletion and service recovery | #8 trace-project operator with external Langfuse operator and #6 | Project and credentials are inventoried privately; active external recovery and approved content policy are incomplete. |
| CPA OAuth/configuration and provider execution recovery | CPA resource owner with #6 | Candidate restore intentionally used dummy CPA settings; external CPA recovery was not exercised. |
| Version upgrade and rollback | #6 with candidate operator | Same-pin restore passed; cross-version migration, PITR and rollback rehearsal remain outstanding. |
| Personal key issuance and accounting epoch | Production owner with native LiteLLM operator | New keys were not issued; old group-owned history remains under its original semantics. |
| Cutover approval/window and rollback authority | Production owner | No approval or ingress switch exists. |

## Required evidence sequence

1. Approve custodians, retention/deletion values, backup location/cadence and
   recovery objectives for each selected state and secret.
2. Complete external CPA/Langfuse recovery and protected off-host retrieval.
3. Rehearse the selected version upgrade and pre-upgrade-snapshot rollback on a
   new isolated clone.
4. Approve personal key issuance, private distribution, old-history access and the
   new accounting epoch.
5. Approve a cutover window and rollback authority.
6. Execute cutover only within that approved window, then record the essential
   checks and rollback-window outcome.

No step in this matrix authorizes production traffic, queue reads, telemetry replay,
request mirroring or deletion of old history.
