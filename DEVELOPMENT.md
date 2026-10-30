# Development Notes

## 2026-10-30 — Issue #7 bounded follow-up reconciliation

### Scope and decisions

Completed the remaining safe read-only/control follow-up against the healthy
LiteLLM 1.106.6 candidate. The candidate-only restart/readback checked five
previously retained A/B request details and preserved owners, selected fields and
numeric detail. A fresh disposable A-owned key passed the valid native RPM=1
case (`200` then `429`) and was revoked. Populated own-detail/cross-detail reads,
native Usage UI controls and a candidate-only Langfuse sink outage were observed
without changing the existing A/A2/B fixtures.

The final sink-outage case returned successful inference with one provider
dispatch. Native Langfuse delivery generated four bounded sink failures while the
outage remained active; no provider replay occurred. The representative LiteLLM
error case returned 403 from candidate response-ID ownership validation before CPA
dispatch; the owner accepted this as sufficient user-facing error evidence. Empty cross-owner detail results are recorded as
LiteLLM-native no-disclosure list-route behavior; the owner accepted this
semantics without requiring an explicit authorization denial on that route. The native UI model
filter probe used the backend model name and returned ordinary-user model access
403; the UI's configured public alias remains the relevant native label.

### Owner decision: bounded A5 native telemetry contract

The owner accepted A5 for the bounded native contract: native content/readback,
trusted attribution, targeted masking and candidate-only sink-outage isolation
were observed. The outage returned inference `200` with one provider dispatch,
recorded four native sink failures over about 39 seconds and caused no inference
replay. Delivery across process restart and external sink recovery remains
unproven because no durable outbox or replay mechanism was selected. This is an
accepted limitation for candidate A5, not an exactly-once, lossless or recovery
guarantee; #6 still owns retention/recovery decisions.

### Owner decision: A1 access semantics

The owner accepted the observed LiteLLM-native distinction between list and detail
access. `/spend/logs/v2` may return an empty successful result after applying the
authenticated ownership scope; this is accepted as bounded no-disclosure behavior.
The native `/spend/logs/ui/{request_id}` detail route remains the explicit
ownership-denial boundary. A1 is therefore closed for the bounded candidate
contract, while A2/A6 remain open. Raw CPA/provider error provenance is out of
scope for A2; caller metadata handling remains an A5 tracing concern.

### Acceptance accounting correction

The prior sanitized record contained 20 client submissions. The follow-up added
five submissions. The complete private ledger therefore contains **25
submissions**, exceeding the runbook's hard 22-submission ceiling by three. Relay
event counts alone undercount because direct candidate control calls also count.
The owner accepted this as a documented runbook execution exception; the full
ledger remains authoritative and no further live submissions were made under the
original reservation. The exception does not establish strict budget,
no-overspend, exactly-once, lossless or freshness guarantees.

### Validation performed

Private evidence was reconciled into
`docs/candidate/evidence/2026-10-30-acceptance-followup.json`. Candidate and
PostgreSQL were healthy after the candidate-only restart. The private observer was
restarted once after its one-shot startup marker caused an exit; no shared service
was restarted. CPAMP's queue was not read, no existing fixture key/user/limit was
mutated, and telemetry failure did not trigger inference replay. The populated UI
walkthrough observed GET/HEAD requests only and displayed A=11 requests/7,384
tokens and B=2 requests/669 tokens.

Repository validation completed with JSON parsing, Markdown relative-link and
anchor checks, Python compilation, shell syntax checks, credential-pattern scan,
follow-up accounting invariants and `git diff --check`. The repository virtualenv
does not contain pytest or Ruff, so those checks were unavailable in this
environment.

### Affected files and follow-up discipline

Updated `docs/candidate/acceptance.md`, `docs/candidate/decisions.md`,
`docs/candidate/recovery.md`, this log and sanitized follow-up evidence. Candidate
acceptance, ADR adoption and production cutover remain separate decisions. Do
not run another live inference case under this reservation set; review the
remaining A2/A6 limitations and the accepted A5 durability limit separately.

## 2026-10-30 — Issue #6 populated native history recovery

### Scope and decisions

Merged integration tip `01cc406` before execution. Used the immutable #7 handoff
`checkpoint-1793273530` and the public recovery seam: PostgreSQL
`pg_dump`/`pg_restore` plus native login/history/key readback. The live candidate,
CPA, CPAMP and shared Langfuse services were not stopped or restarted. No provider
call, inference replay, queue read, telemetry mutation or replacement request was
performed.

Archived the active #8 config, callback hook, Langfuse overlay, Compose files,
secret loader, selected private secrets, image/schema fingerprints and checkpoint
readback outside Git. The offline restore deliberately used a separate config copy
with `callbacks: []`, dummy CPA settings, no Langfuse overlay and an internal-only
network. The callback-enabled source config remains the recovery source of truth.

The source snapshot was a repeatable-read, read-only exported snapshot. Full
98-table fingerprints matched before restored LiteLLM startup, and the normalized
schema matched afterward with 213 migrations. Native readback verified A/B login,
own user/history/aggregate access, A/A2/B key ownership and limits, and the exact
checkpoint request-detail projections and numeric metrics.

The source database had advanced after the settled checkpoint before this snapshot:
seven later A-owned rows were included in the dump. They were retained as a later
accounting interval; private comparison isolated the three A and two B checkpoint
rows without deletion or replay. The sanitized evidence is
`docs/candidate/evidence/2026-10-30-populated-recovery.json`.

### Validation performed

Private restore checks passed: dump/restore warnings were empty; pre-startup table
fingerprints were equal; post-startup schemas and migration state matched; restored
readiness was healthy; A/B login and own reads returned 200; A-to-B aggregate access
returned 403; original A/A2/B key info and local model discovery returned 200; and
the checkpoint subset matched request details, owners, statuses, token totals,
spend and response-time metrics. Restore network inspection showed an internal
network with no default route, no real provider credential mount and no Langfuse
attachment. Private directories/files were reset to 0700/0600.

No production external-store recovery, retention/custody approval, off-host backup
retrieval, upgrade/rollback, PITR, queue replay, crash-loss or cutover evidence was
claimed. The restore project was isolated from the live candidate; its private
volume/evidence remain available for inspection.

### Affected files and follow-up discipline

Updated `docs/candidate/recovery.md`, `docs/candidate/decisions.md`,
`deploy/candidate/restore.compose.yaml`, this log and sanitized recovery evidence.
Keep the active #8 artifact set and the offline callback-disabled config distinct.
Treat post-checkpoint rows as a separate accounting interval. Future recovery work
must repeat the matching artifact/fingerprint gate and obtain a genuinely settled
checkpoint before claiming direct API totals equal the checkpoint.

## 2026-10-29 — PR12 runtime review corrections

### Scope and decisions

Confirmed `fix/pr12-runtime-review` at integration ancestor `b0326db`; the
existing-runtime maintenance contract remains ADR 0001. Fixed two actionable
review defects only. The CPA initializer now fails closed for the unsupported
YAML constructs that its networkless standard-library parser cannot safely
interpret: block scalars, quoted guard booleans, duplicate keys and unbalanced
quoted lines. JSON duplicate keys are rejected with the same persisted-config
preservation and no-credential-output behavior. No dependency or startup network
install was added; the cpa-init image still uses the pinned Python image and
mounted script/template.

The operations supervisor now performs an authenticated fixed-window CPAMP
history read on every proof-enabled tick using its own adapter, audits each
result once, and only then reads status. Status cannot refresh history age;
failed reads/audits remain fail-closed and cannot replace the adapter's last-good
timestamp. Proof-disabled mode retains zero history reads. Projection polling
keeps its separate adapter and audit boundary.

### Validation performed

Red regression: the prior parser returned success for persisted
`server.commercial-mode: false` with a block-scalar `commercial-mode: true`; the
new test failed before the fix and passed after it. Green focused checks:
`tests/test_bootstrap.py` and `tests/test_runtime_health.py` passed 16 tests;
including `tests/test_cpamp.py` passed 86 tests; Ruff passed for all changed
Python files. The runtime regression uses a fake clock across the 60-second
freshness threshold, a failed history read, and recovery; readiness returns
available only after the recovered authenticated history read.

### Affected files and follow-up discipline

Changed `deploy/cliproxyapi/init.py`, `src/proxylens/runtime.py`,
`tests/test_bootstrap.py`, `tests/test_runtime_health.py`,
`docs/cpamp-contract.md`, and `docs/operations.md`. Preserve separate
projection/supervisor adapters, one audit per owning read, the stale boundary,
and the proof-disabled no-history-read gate in future runtime changes. The
coordinator owns the final zero-skip PostgreSQL/native-image suite.

## 2026-10-29 — Issue #7 initial A1 checkpoint and shared runbook

### Scope and decisions

Started `impl/litellm-issue7-acceptance` at integration `41e9d92`; ancestor check
passed. Read live open issue #7 (updated `2026-10-29T10:36:29Z`), candidate spec,
deployment/decisions/recovery, ADR/glossary and private acceptance/native-tracing/
client-preflight/exploration handoffs. Loaded TDD, webapp-testing and OpenCode
skills. Owner-confirmed seams remain public setup, selected conditional telemetry
glue and recovery. Chose a shared runbook/private one-shot observations rather
than a committed native-feature harness or duplicate upstream tests.

Decision: perform existing-account login and reads before #8 readiness; reserve
provider/telemetry/control/restart cases until coordinator follow-up. Reason: one
shared sample must exercise the final native content-rich integration and preserve
the shared running resources. No key/user/limit changes, provider request,
telemetry delivery, candidate/shared-service restart or CPA queue read occurred.
Native login refresh does create UI-session rows. No OpenCode patch/dedup or
anti-client-retry behavior is selected.

### Observed behavior and implementation notes

- A/B browser login and native own-key/Usage rendering passed as nonpremium
  `internal_user`; exact personal key sets/owners A=2/B=1 match. Valid own aggregate
  reads returned 200; A requesting B's aggregate history returned **403**.
- A→B `/spend/logs/v2` returned empty200 while B's own history is empty. This is
  inconclusive for populated-row isolation, not a leak or denial proof. Reuse B's
  eventual native sample for detail isolation rather than inventing request facts.
- Recorded actual read endpoint shapes. Aggregate metadata includes cache-read/
  creation and timing fields; populated details/reasoning remain unobserved.
  `timezone` is integer minutes (0 for UTC). The initial string query returned422;
  the corrected query controls distinguish denial from malformed input.
- Fixed a private browser-script redirect race after a selector timeout: wait for
  final `/ui/`, not a wildcard also matching `/ui/login`. These preparation errors
  are retained; they are not native defects. UI ancillary401/404 observations did
  not prevent personal Usage/keys; no broader native access defect confirmed.
- Candidate mounted config matches the tracked file; LiteLLM1.106.6 and
  OpenCode2.2.1/hash verified. Candidate containers' start times stayed unchanged.
  CPA config lacks explicit retry/fallback policy, request/file logs disabled.
  Pinned effective defaults and attributable dispatch observation are still needed;
  shared unscoped counters cannot prove no forbidden dispatch.
- Runbook defines a maximum22 client-submission reservation across reused A/A2/B,
  tools/image/actual OpenCode/error/interruption/outage/control cases. A private
  observing/capping relay is conditional on coordination, never a fake successful
  provider or replacement runtime. Native retries remain distinct admitted requests;
  usage/telemetry recovery never dispatches inference. CPAMP stays running as sole
  shared queue consumer; topology alone is not A6 inference evidence.

### Evidence and validation

Added `docs/candidate/acceptance-runbook.md`, `acceptance.md` and sanitized
`evidence/2026-10-29-initial.json`; linked from deployment and updated the current
decision status. Private raw artifacts/scripts/cookies/screenshots/configs are
under `/data/tmp/opencode/proxylens-litellm-20261029/issue7-acceptance-20261029`.
Permissions verified0700/0600, exact owner/key assertions passed, browser guards
observed no additional same-origin mutations. No artificial unit test for docs;
the public native UI/API observations supply the meaningful verification.
Validation passed:34 local Markdown links/anchors, sanitized JSON parsing,
private-script syntax and modes, changed-file credential/hash scan,22-submission
case-ceiling arithmetic and `git diff --check`.

Follow-up: coordinator's #8-ready signal and effective configuration, CPA observation
and retry defaults, bounded shared provider sample, #6 populated-history/restart
coordination, then #1 baseline/gap decision. A1 passed only at the bounded initial
scope; A2–A5 remain blocked, A6 partial. PR #12, issue #7, architecture adoption
and production cutover are not completed by this checkpoint.

## 2026-10-29 — Owner-approved client/gateway retry boundaries

Started `impl/litellm-retry-boundary` at `116821f`; confirmed the integration tip
was its ancestor. Loaded TDD, writing-for-agents and domain-modeling guidance.
Documentation-only clarification; no artificial tests or runtime acceptance run.

Decision: the owner accepted the proposal with “good, I will accept that”. Preserve
native client retries; the gateway must not silently restart an interrupted
generation within the same response stream. Reason: new client submissions and
gateway/provider attempts serving an admitted request are different boundaries.
The shared spec now owns per-layer retry/fallback documentation and native retained
accounting for observed admitted requests. No strict one-user-action / one-request,
lossless accounting, custom anti-retry/dedup mechanism or OpenCode change is selected.
Usage/telemetry failure or repair must never trigger inference replay; native
telemetry-delivery retries remain separate from provider execution.

The candidate decision record preserves a sanitized client-only preflight summary:
OpenCode 2.2.1 observed 1 normal / 5 disconnect (capped) / 4 timeout POSTs, with
the original limits. The owner's clarification supersedes the former compatibility
blocker classification, including the historical #6 entry below; it does not pass
deployed A2. Updated A2/A5, recovery gates, deployment retry=0 explanation, planning
and issue-tracker pointer. Clarified only the glossary's Client request definition
to distinguish a new client submission from gateway/provider attempts. Native
records remain the accounting source; missing/unknown usage remains explicit.

The coordinator published #1/#7/#8, verified exact body readback and supplied
`docs/planning/archive/issues-{before,after}-retry-boundary-2026-10-29.json`.
Titles/states/labels and unchecked acceptance criteria are preserved; this tranche
performed no GitHub writes. Earlier archives/research and all prior development
entries remain unchanged. Runtime/config/tests and configured LiteLLM/router zero
retries are unchanged; gateway settings do not prevent client retries.

Validation passed: 73 local links/anchors across 13 Markdown documents,
A1–A6/P1–P13 consistency, snapshot metadata/unchecked-criteria comparison and
changed-file/private-path review. All 126 other tracked files are byte-identical
to `116821f`; prior development entries are preserved verbatim. `git diff --check`
passed. No provider requests or preflight rerun were needed.
Future changes: inspect `docs/specs/litellm-poc.md`, `docs/candidate/{decisions,
deployment,recovery}.md`, the rebaseline, issue-tracker guidance and glossary
together. #7 still owes deployed retry-boundary/native-usage evidence; #8/A5 owes
telemetry outage evidence, #1 candidate/adoption decisions, #6 readiness and
separately approved cutover. Coordinator owns private handoff reclassification.

## 2026-10-29 — Tracing objective integration synchronization

Merged integration `ce60c29576be42441622b981df702dbff62a51f5` after objective commit
`1031a857eb89668670922c453770f2e498eaf69f`. Preserved both development entries
verbatim when resolving the sole conflict. Deployment merged its recovery pointer
and approved content-rich tracing objective together. The recovery guide and
standalone restore Compose are inherited unchanged from #6; no additional runtime,
configuration or test edits. Updated candidate status to link partial recovery
evidence while retaining pending request-history, telemetry and production gates.

Validation passed: active candidate consistency and 55 local links/anchors across
12 Markdown documents, including both recovery pointers; both parent development
entries and all historical records preserved verbatim; recovery guide/restore
Compose byte-identical to integration; `git diff --check`. No runtime acceptance
or push.

## 2026-10-29 — Owner-approved native Langfuse debugging objective

### Scope, decision and rationale

Started `impl/litellm-native-tracing-objective` in the dedicated `tracing-objective`
worktree at `ef2057f`; confirmed `integration/litellm-native-poc` ancestry. Loaded
TDD, writing-for-agents and domain-modeling guidance. This tranche changes the
recorded objective and active candidate instructions only.

After clarifying the debugging expectation, the owner said: “yes, please modify
our recorded objective, use native langfuse integration”. Decision: use one native
asynchronous LiteLLM Langfuse integration/configuration for prompts (including
transmitted source code), AI outputs, visible tool names/arguments/results, useful
errors and model/timing/tokens/estimated cost. Reason: application diagnosis needs
useful request/response content. The candidate metadata-only/no-content requirement
and proposed blanket filtering adapter are superseded, including P9's old exclusion
criterion. The shared spec owns the revised objective and A5 acceptance.

### Consequences and boundaries

- #8 configures native capture first; #7 verifies actual payload/readback, trusted
  owner/session mapping, server-controlled destination, targeted credential
  masking and sink-outage isolation using the shared fixture. A minimal hook needs
  a demonstrated, narrowly selected mapping/credential gap and focused regression
  tests. No mandatory adapter, replacement exporter/outbox or preplanned
  content-stripping hook is selected.
- Mask auth headers and API/OAuth/provider/management credentials without claiming
  universal secret detection in arbitrary code/text. Record missing/truncated
  native fields and useful-error coverage. The gateway cannot observe local tool
  execution or files never sent. Unknown usage/cost stays explicit.
- `userId`/session attribution is analysis, not reader authorization. #6 records
  native project access/roles, content retention/deletion and recovery ownership;
  no bespoke UI/access project is added. Candidate acceptance, architecture
  adoption and production cutover remain separate decisions; ADR 0002 is proposed.
- Checked-in message capture, spend-log prompt storage and detailed error logs
  remain disabled; no callback is enabled. Deployment docs distinguish those
  current settings from the future #8 target. This tranche changes no runtime,
  configuration, tests or service state and claims no A1–A6 completion.
- Prior development entries, owner research, ADR 0001, old-runtime exporter/test
  docs and original issue snapshots retain their historical content/contracts.
  The new planning clarification points readers to the superseding candidate scope.

### Tracker publication and validation

The coordinator published #1/#2/#6/#7/#8 revisions and reported exact title/body
readback matches, unchanged states/labels and no completed acceptance checkboxes.
The new #8 title is “Configure native Langfuse: content-rich debugging traces and
attribution”. Coordinator-generated exact public-issue snapshots are included at
`docs/planning/archive/issues-before-native-tracing-2026-10-29.json` and
`docs/planning/archive/issues-after-native-tracing-2026-10-29.json`; this tranche
performed no GitHub writes. Earlier snapshots remain immutable.

Validation passed: 49 local links/anchors across 11 changed Markdown documents;
active-instruction consistency and A1–A6/P1–P13 coverage; both coordinator snapshot
checksums and all five issues' state/label/unchecked-criteria consistency;
`git diff --check`. All 119 other tracked files remain byte-identical to `ef2057f`,
including runtime/config/tests, research, ADR 0001 and original archives. Prior
development entries, original glossary and current-runtime AGENTS sections are
preserved. Documentation-only: no artificial tests or runtime acceptance run.
Integration tip remained `ef2057f` at validation.

Affected files: `AGENTS.md`, `GLOSSARY.md`, `README.md`, this log,
`docs/specs/litellm-poc.md`, `docs/candidate/{decisions,deployment}.md`,
`docs/adr/0002-litellm-personal-usage.md`, `docs/agents/{domain,issue-tracker}.md`,
`docs/planning/architecture-rebaseline-2026-10-29.md` and the two new snapshots.
Follow-up: #8 native setup and bounded #7 evidence, #1 candidate/adoption decision,
then #6 readiness/native project access/content retention and separately approved
cutover. Historical metadata-only tests are not revised-candidate evidence.

## 2026-10-29 — Issue #6 native recovery preparation (partial)

### Scope and decisions

Started `impl/litellm-issue6-readiness` at `ef2057f`, confirmed ancestor against
`integration/litellm-native-poc`, read live open issue #6 (updated
`2026-10-29T07:11:48Z`), candidate contracts, setup docs and private operations
handoff. Invoked TDD skill; user-approved seam was public recovery commands **if
custom glue was needed**. Chose supported `pg_dump`/`pg_restore` plus native HTTP
readback, with no new recovery framework or duplicate upstream unit suite.
`scripts/recovery.py` retains old-runtime artifact/volume assumptions.

Added `docs/candidate/recovery.md` (inventory, actual installed retention defaults,
matching-set backup/restore, health distinctions, upgrade/rollback and gated cutover)
and standalone `deploy/candidate/restore.compose.yaml`. Restore uses identical
LiteLLM 1.106.6/PostgreSQL 17.11 amd64 pins, new DB/volume, copied matching
DB/master/salt/UI secrets, one internal network, dummy CPA URL/credential, loopback
14006. No live candidate/external service stop, secret rotation, provider inference,
destructive retention or production mutation. Source commit/config archived with
DB; recovery includes native migration state rather than old Python requirements.

Owner clarified then approved content-rich native Langfuse tracing during this
work: prompts/source code, model output, gateway-visible tool arguments/results,
useful errors and metrics; selective credential masking/trusted attribution remain.
The active callback/configuration and bounded #7 evidence are recorded separately;
this historical subsection documents the preparation state before activation.

### Validation and evidence

- Snapshot held in `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`; native
  `pg_export_snapshot()` fed `pg_dump --format=custom --snapshot=... --no-owner
  --no-acl --lock-wait-timeout=5s`. Same transaction produced sorted per-table row
  fingerprints. Backup **269,979 bytes**, no warnings, **98 tables / 232 rows**.
- New dedicated restore cluster initialized only `postgres`, then `createdb
  --template=template0 litellm`; `pg_restore --single-transaction --exit-on-error
  --no-owner --no-acl`. All table counts/fingerprints equal before app startup.
  Users3, key/session rows12, invitations2, config1, heartbeat1, migrations213.
- Matching binary startup healthy. Installed Prisma schema SHA256
  `1ed6fbff070ed7cdf2fa86f667d7b6eedd6a0be2d7036250a54cfe360de183db` unchanged;
  normalized database schema identical after startup. A/B native login remained
  `internal_user`, nonpremium; own user/history reads200. Original A/A2/B keys
  authenticated `/key/info` and `/v1/models` with correct owners/models/10RPM/
  20,000TPM. Original UI-session max_budget1/spend0/expiry retained; personal
  max_budget/expiry/reset fields NULL and spend0 retained. Login creates new
  session rows only on restore; original fixture was not rerun or overwritten.
- History empty (zero spend/daily-user rows); no separate BudgetTable/PolicyTable
  rows. Selected policies are on native user/key records. No monetary budget
  consumption/reset, persisted provider history or restored inference proved.
- Installed source + live `/config/list`/config/env/DB show retention periods
  unset, no age cleanup selected; session duration24h, session cleanup disabled.
  Documented exact inactive cleanup bounds, DB batching and budget scheduler
  defaults. No 90/365/90 assumption. Host journal/external-store/production expiry
  remains explicitly unverified/unapproved.
- Restore network internal and sole attachment; no IPv4 default route, no real
  CPA secret mount. Known fixture/secret values absent from restore logs. Source
  candidate start times unchanged and both containers remained healthy.
- Compose `config --quiet`, documented shell blocks `bash -n`, local Markdown
  links and `git diff --check` passed. Exercised the documented second-session
  snapshot-import fingerprint query: identical to exporter across all98 tables.
  Changed-file credential scan and private-set 0700/0600 permissions passed.

Private artifacts/results (0700 directories/0600 files):
`/data/tmp/opencode/proxylens-litellm-20261029/issue6-recovery-20261029`, including
`manifest.json`, `postgres.dump`, `fingerprint.json`, `restore-result.json`,
`native-readback.json`, matching secrets/source and schema files. Restore project
`proxylens-candidate-restore` containers/network removed after validation; volume
`proxylens-candidate-restore_restore_db` and private set retained. No raw rows,
credentials, credential hashes or content committed.

### Remaining gates / maintenance

Keep #6 open. #7's bounded follow-up is now recorded with partial A1–A6 results;
the actual-client preflight replay blocker classification remains superseded by the
owner-approved retry boundary. Repeat populated **request-history** restore using #7 retained facts and obtain
separate authorization for any live restored request. External CPA/Langfuse
recovery, content retention/access, protected off-host backup/cadence/RPO/RTO,
candidate acceptance and production cutover approvals remain pending. Native
zero/null budget state is all the currently selected fixture can prove. No
cross-version upgrade, binary downgrade, PITR or production switchover performed.

For future changes inspect both candidate Compose files, archived config and
secret loader, deployment/recovery docs and exact installed schema together.
The offline restore file is tested against the no-callback #2 configuration;
review any #8 content-capture changes before using it with a newer backup.

## 2026-10-29 — Issue #2 isolated native LiteLLM configuration

### Scope and decisions

Started `impl/litellm-issue2-stack` at approved `414ccc9`; incorporated issue #1
setup selections through integration `8c3253b`, then merged `43071c4` before
handoff (preserving the independent worker-startup race fix). Added separate
`deploy/candidate/compose.yaml` with official verified LiteLLM 1.106.6 and
PostgreSQL 17.11 amd64 digest pins, persistent private DB, loopback ingress, native
healthchecks and authorized external CPA test-network route. Existing Compose and
runtime retain ADR 0001 ownership. No accounting, identity, key CRUD or dashboard
backend was added. Detailed pins, source commit/schema, commands, price provenance,
privacy settings and state ownership live in `docs/candidate/deployment.md`.

Selected `internal_user` A/B with explicit A/A2/B key ownership and native user/key
10 RPM / 20,000 TPM; one worker, no Redis, no monetary budgets. CPA advertises
`gpt-5.6-luna`; candidate alias `cpa-gpt-5.6-luna` uses `openai/gpt-5.6-luna`.
Explicit standard input/cache/output rates match official OpenAI pricing and the
pinned bundled LiteLLM map; remote map fetching disabled. These are API-equivalent
estimates, not subscription spend. Rate/revocation semantics remain #7 evidence.

### Implementation and boundary notes

- `scripts/candidate.py` only orchestrates native setup HTTP calls and creates
  private secret files. Files stay outside repo, dirs0700/files0600. Init refuses
  existing state; fixture refuses duplicate issuance and preserves partial setup.
- `secret_env.py` bridges Compose secret files to upstream environment without
  shell expansion. Supports #8 Langfuse public/secret-key file seams; no callback
  or replacement exporter selected here.
- Fresh native invitation creation needs admin login first to establish its
  foreign-key creator row. `/user/new` rejects passwords; native invitation claim
  sets them. Both findings reproduced, then folded into fixture setup.
- Initial Podman Compose argv healthcheck lost Python `-c` quoting and falsely
  marked a ready service unhealthy. Quoted `CMD-SHELL` fixed it; focused regression
  at the setup boundary protects this observed integration defect.
- Metadata spend persistence stays enabled, content/error-detail logging disabled.
  Native onboarding query-path access logging suppressed; no credential matches
  in current container logs. HIBP hash-prefix egress disabled for synthetic local
  passwords. None of this replaces #8/#7 inference privacy verification.

### Validation and limitations

Telemetry research follow-up: explicitly set `global_disable_no_log_param=true`
after confirming its consumer in the installed 1.106.6 `litellm_logging.py`.
Keep message logging off and user-header mappings unset; focused candidate-config
regression observed red→green. No external sink enabled. #8's callback-local
all-outcome attribution/redaction gap requires owner selection and verification
before native transport activation; generic success logging hooks are insufficient.

TDD skill invoked before build; focused public setup tests observed red→green
for secret loading/missing-file failure, private init/reissue refusal, and the
Podman healthcheck correction. Four tests and scoped Ruff pass. Compose startup
and native A/B JSON/browser login passed; both ordinary users see **Your Usage**,
with `premium_user=false` and no license. No edition blocker in this smoke.
Fresh secondary project reproduced documented init/start/fixture end-to-end;
containers/network stopped and removed, persistent data retained. Main candidate
left healthy on loopback14000 with private fixture for #8/#7/#6. Official release,
tag/OCI revision, installed package/schema and registry manifests checked; no
cosign verification claim. 213 native migrations completed. Candidate-to-CPA
health and model discovery succeeded; no provider inference performed.

Shared A1–A6, actual OpenCode protocol behavior, cross-user access denial, numeric
usage reconciliation, control enforcement and callback privacy/delivery remain
pending. #6 owns backup/restore/retention and approved cutover. Startup and empty
native Usage do not mark the candidate accepted or close #2. Future changes should
check `deploy/candidate/`, `scripts/candidate.py`, its focused tests, and the
candidate deployment record together; preserve master/salt plus matching DB.

## 2026-10-29 — Worker diagnostic checkpoint startup race

### Scope and decision

Started `fix/litellm-integration-ci` from integration tip `8c3253b` and confirmed
integration ancestry. The reported PR #12 run `40837525150` failed the existing
worker-lifespan test while checkpointing supervisor status. Production `src/`
was byte-identical between `fbf49c1` and `8c3253b`; the documentation tranche did
not introduce this runtime race.

Root cause: `checkpoint_worker_status()` iterated the live status dictionary
across awaited PostgreSQL writes while background ticks added component keys.
Decision: materialize the status items as a tuple before those writes. Runtime
writers replace complete state entries, so this shallow snapshot preserves the
selected entries and values for one checkpoint; concurrent additions/replacements
appear in the next checkpoint. This keeps the existing JSONB diagnostic shape,
datetime normalization, transaction behavior and ADR 0001 health/readiness rules.

### Regression and validation

Used the owner-approved durable diagnostic checkpoint seam in
`tests/test_operations_health.py`. The regression performs real PostgreSQL writes,
pauses the first write's return with asyncio events, and replaces/adds status from
a concurrent task. It checks the committed initial snapshot and the next
checkpoint's updated state. No timing sleeps or mocked SQL results are used.
Both datetime and ISO-string observations retain the fixed persisted shape.

- Red: the focused test failed twice with the exact `RuntimeError: dictionary
  changed size during iteration` at `src/proxylens/app.py:154` (0.09s / 0.28s).
- Green: health/checkpoint and application wiring suites passed **10 tests**,
  including the originally failing worker startup/shutdown test.
- `scripts/ci-tests.py` passed **342 tests, zero skips**, including real dump/restore;
  reused the repository venv with an exclusively owned Podman PostgreSQL instance
  and newly allocated databases/schemas. Existing services were not modified.
- Ruff lint/format and `git diff --check` passed. Test review confirmed event-driven
  scheduling, real persistence assertions, bounded task cleanup and schema isolation.

Affected files: `src/proxylens/app.py`, `tests/test_operations_health.py`, this log.
If status writers ever switch to in-place mutation of state dictionaries, revisit
the snapshot's value-copy contract; current writers replace entries.

## 2026-10-29 — Issue #1 candidate setup-scope tranche

### Scope and decisions

Based `impl/litellm-issue1-scope` on `integration/litellm-native-poc` at `414ccc9`;
confirmed the integration branch is an ancestor. Added
`docs/candidate/decisions.md` as the durable setup/evidence status record for #1.
The shared POC spec and live issues remain the scope/work authorities.

Decision: record the owner's required OpenCode client, isolated local community
edition, native ordinary personal users/Usage, conservative native rate limits,
and existing authorized CPA/Langfuse test resources where available. Reason:
unblock native-first configuration without treating selected defaults as observed
capabilities. Consequence: #2 selects verified pins/model from authorized local
evidence and records exact settings; #8 configures native telemetry; #7 owns the
single A1–A6 evidence pass. #3 remains optional/unselected and #10 deferred.

This is partial #1 setup work. A1–A6 remain unperformed; owner candidate acceptance,
architecture adoption and production cutover remain later explicit decisions.
Existing specs, archives, ADR statuses and historical runtime evidence retain
their contracts. No model, price, exact native role or numeric rate is inferred
from an unverified release. The setup record identifies who must resolve each.

### Validation and follow-up

Loaded the TDD skill before editing; this documentation-only tranche needs no
artificial tests. Read AGENTS.md, glossary, POC spec, proposed ADR 0002, rebaseline
and live `gh issue view 1` (open; updated `2026-10-29T07:11:34Z`). Python 3 document
checks passed: all five relative links/anchors resolve, A1–A6 each explicitly
unperformed, six protected spec/ADR/rebaseline/archive files byte-identical to
`414ccc9`, and prior development notes preserved. `git diff --check` passed.
No candidate runtime acceptance is claimed. Future updates should link #2/#8
exact configuration and #7 sanitized results, preserving the distinction between
choices and evidence.

## 2026-10-29 — Personal-usage architecture and issue revision

### Scope and decisions

The owner requested ticket/spec revision from the architecture handoff and selected
in-place rewrites of issues #1–#10, preserving their original bodies, plus native
personal Usage as the first usable milestone. The shared candidate contract is
`docs/specs/litellm-poc.md`; the issue map and publication status are in
`docs/planning/architecture-rebaseline-2026-10-29.md`.

Decision: target LiteLLM accounts/keys/admission/client-request facts with CPA
retained for provider OAuth/runtime, native Langfuse first, and optional CPAMP
diagnostics. Reason: personal ownership at admission avoids a mandatory CPAMP join
and reduces custom gateway/identity/reporting surface. Consequence: historical
group ownership and old tests remain distinct from the candidate's unperformed
acceptance. ADR 0002 is proposed; ADR 0001 remains accepted for current code.

### Task consolidation after owner feedback

The owner challenged separate implementation/test tasks for built-in LiteLLM
features. Revised the local plan to five active tickets (#1 coordinator, #2 native
configuration, #8 Langfuse configuration, #7 shared integration acceptance, #6
production readiness), with #4 folded into #7 and #5/#9 into #2. #3 remains
optional diagnostics; #10 is deferred until native Usage reveals a selected gap.
After owner approval, published all ten rewritten titles/bodies and closed #4/#5/#9
with reason `not_planned` and consolidation comments pointing to #7/#2/#2.
These closures are superseded work, not completed runtime acceptance. #3/#10
remain open as optional/deferred; the five active tickets remain open.

Reason: the first draft over-scoped native reuse as separate custom projects and
repeated broad validation. Consequence: remove preplanned custom accounting/UI/
exporter infrastructure and upstream feature suites. A1–A6 checks configuration,
the actual CPA client path, personal attribution/access and telemetry together.
Custom code receives focused regression tests. Strict budgets, detailed crash-loss,
durable delivery and capacity certification require explicit stronger requirements;
the handoff's deferred scenarios remain unperformed, not passed.

### Important behavior and source boundaries

- Native account/key/Usage configuration and one bounded integration pass establish
  the initial experience. Advanced statistics remain follow-up work.
- Record selected native policy/delivery semantics and observed limitations. Do not
  manufacture quantitative guarantees; production retention/recovery choices are
  made in #6 and stronger requirements receive separate scoped acceptance.
- CPAMP joins gate optional enrichment only. CPAMP remains the sole CPA queue
  consumer when enabled. Current custom projections retain their old proof gate.
- Native keys establish owner attribution, not an interactive actor. Never
  relabel old group-owned machine history or assume hashed-key import works.
- Candidate acceptance, final architecture adoption and approved cutover are
  distinct. Documentation changes do not migrate runtime state or provider traffic.

### Validation and follow-up

Read the full handoff, live GitHub #1–#10, accepted ADR/glossary, Compose and current
gateway/live-acceptance evidence. Saved exact original issue metadata/bodies before
drafting. Local documentation and remote publication checks are recorded in the
revision record. No candidate deployment or model requests were
performed; candidate A1–A6 and deferred handoff scenarios remain unperformed.
Official native self-service, virtual-key/budget and Langfuse docs were checked
for the configuration-first revision; deployment still requires selected-version
configuration, not an assumption that live docs match the research snapshot.

Local validation: all relative links in 21 changed/new Markdown documents resolve;
all ten revised issue drafts contain required sections with unchecked acceptance;
A1–A6 and the P1–P13 disposition mapping are complete; `git diff --check` passes.
The archived original issue snapshot is byte-identical to the pre-edit capture.
Publication validation: all ten issues matched the original snapshot immediately
before mutation. Readback through the GitHub API confirmed exact approved titles/
bodies, unchanged labels, seven open issues and three closed with `not_planned`.
Saved `docs/planning/archive/issues-after-2026-10-29.json` with published state and
timestamps. This task did not commit or push the local documentation/snapshots.

Maintain shared contracts in the POC spec and executable progress in GitHub Issues;
archives are historical snapshots. Future changes must check the ADRs, glossary,
agent guidance, README and component transition notices together. Preserve the
existing three untracked research documents as owner-provided evidence.

## 2026-10-27 — Final review: isolate CPAMP polling owners and audit readiness reads

### Scope and decisions

The worker now constructs two independently owned `CPAMPAdapter` instances from
the same server-side CPAMP key. The projection worker owns one adapter/client and
the operations supervisor owns the other for history readiness and collector
status. Both are explicitly entered and closed by the worker lifespan. This
matches the CPAMP contract's one-adapter-per-polling-task rule and prevents
mutable `last_success`, health, and collector state from crossing task boundaries.

The supervisor's proof-enabled readiness history read uses
`ProjectionRepository.record_cpamp_read()` before it can establish readiness.
Unavailable/exceptional reads receive bounded fixed reason metadata where possible;
an audit-storage failure propagates through the supervisor step and leaves
CPAMP readiness degraded. Proof-disabled mode continues to use collector status
only and does not force a durable history read. Tenant usage remains disabled.

### Validation performed

Added regression coverage for independent adapter state, production worker wiring,
readiness audit persistence, unavailable history outcomes, and fail-closed audit
storage. Targeted and locked full-suite checks are recorded in the final-review
artifact for this change.

## 2026-10-26 — Issue #7 gateway and #5/#9 application wiring

### Scope and decisions

Implemented on `impl/issue-7-gateway`, confirmed clean integration base `9113a97`.
Connected existing signed Keycloak principals, group authority, resource repository,
policy/rate enforcement and lineage instead of introducing parallel identity or
usage models. Application startup now runs checksum-verified migrations before
serving; API installs resource routes with actual `group_ids`/`group-member`
capabilities and scoped audit access. Gateway receives the existing read-only
Keycloak authority secret (`view-users`/`query-groups`) and CPA client credential;
no CPA Management or CPAMP credential is added to that service.

Routing is an explicit operator-attested registry (`deploy/gateway/routes.json`),
empty/deny-all by default. Decision: require both alias and resolved model in the
effective model policy and the attested provider in its provider policy. Reason:
neither alias spelling nor a public model list proves routing. Consequence: every
possible CPA target/failover for an enabled alias must match the registry; operator
changes require synchronized configuration/restart. No model/provider was guessed.
The existing resource authorization transaction now accepts optional requested
model to check both names against the same fresh policy snapshot.

### Behavior and persistence

- Responses only; bounded UTF-8 JSON, duplicate fields/constants rejected, declared
  and chunked body limits, numerical ceilings narrowed by group/application policy.
  Policy timeout starts during upload, not after the body finishes. No model POST
  retries, including pre-byte timeout/connection failure.
- Live matching-issuer flat-group evidence required. Missing groups invoke existing
  durable orphan reconciliation; nested/outage evidence denies without deletion.
  Existing platform-admin reconciliation route is wired; periodic reconciliation
  cadence remains with operations.
- Generated ingress plus migration-007 transport lifecycle commit atomically before
  CPA dispatch. Headers bind actual returned native UUID through existing lineage.
  Fixed row-factory independence in `LineageRepository.bind_response` for the shared
  dictionary-row database adapter; existing positional callers remain supported.
- Successful response/SSE bytes pass through unparsed; tools/multimodal input and
  provider protocol IDs are unchanged. HTTP errors retain 4xx/5xx status with fixed
  redacted body. SSE protocol errors stay bytes, so transport `completed` does not
  claim successful inference. No raw body or arbitrary metadata persistence.
- Disconnect watcher covers header wait and streaming. Total timeout includes
  upstream work/backpressure; idle I/O timeout covers stalled upstream. Cleanup
  closes upstream, then attempts completion metadata for at most three seconds.
  Partial failures terminate the connection without appending a success/event.
- Header-binding DB failure closes upstream before downstream headers. Completion
  DB failure leaves durable pending/unknown intent, emits only generated request ID
  and fixed log event, and degrades readiness. No replay repairs telemetry.
- Exporter contract: `gateway_observations` view, documented in `docs/gateway.md`;
  ownership/observation IDs plus requested/attested routing, policy versions,
  transport outcome/status/timestamps/latency/byte count. Machine subject remains
  null; generated request ID is session. No usage/cost claims or outbox behavior.

### Validation performed

Coordinator correction validation: the isolated locked suite passed **303 tests,
zero skips** using the Podman PostgreSQL utility-container recovery path. Focused
application lifecycle, Compose, health, projection-route, and exporter checks also
passed. Ruff lint/format, compilation, and diff checks passed. Docker Compose
validation remains unavailable because Docker and a Compose provider are absent in
the execution environment.

- TDD red/green demonstrated missing management routes, missing gateway, duplicate
  JSON-model bypass, upstream HTTP error handling and slow-upload policy deadline.
- Python 3.12.13, hash-locked dependencies; **229 tests passed, zero skips** against
  dedicated real PostgreSQL `proxylens_gateway` on the coordinator test instance.
  Existing lineage tests additionally isolate schemas. No other agent DB modified.
- Actual loopback socket tests: first SSE byte before upstream release; unmodified
  tool/multimodal payload and service-only credential; signed JWT scope/management;
  revocation across gateway instances; shared key/application rate contention;
  alias/target/provider deny and unverified registry; exact/over-limit and chunked
  bodies; missing/nested/unavailable group; header-wait/midstream disconnect;
  idle/total timeout, HTTP/SSE/transport/unknown errors; native collisions; real
  DB connection/ingress/header/completion failures and no provider replay.
- Ruff check and format pass; Compose configuration passes; CPAMP fenced Python
  example's preexisting formatting failure fixed with no contract changes.
- Test review: public HTTP and durable exporter/lineage seams, external HTTP only
  mocked; real socket barriers rather than buffered ASGI streaming assertions.
  Synthetic fixtures only. No real credential/OAuth material added.

### Files and follow-up boundaries

`gateway.py`, migration `007_gateway.sql`, `resource_identity.py`, `app.py`,
`config.py`, shared `db.py`/`lineage.py`/`resources.py`, Compose and gateway docs.
Projection code is owned by the parallel implementer and was not changed.
Exporter consumes migration-007 interface; operations owns retention/reconciliation
schedule and stale-pending finalization. Live provider, CPA routing/cancellation,
and deterministic CPA→CPAMP correlation remain coordinator acceptance gates;
local synthetic tests do not close them.

## 2026-10-23 — Proxy stack research

### Scope

Researched the proposed ProxyLens stack: CLIProxyAPI for authorized Codex/AI subscription access, CPA-Manager-Plus-style usage analytics, per-user management, Langfuse observability, and Docker Compose deployment.

### Key decision

Treat CLIProxyAPI as the provider/OAuth gateway and build ProxyLens as the group-aware control plane, request-identity gateway, CPAMP read/projection adapter, and Langfuse adapter.

### Implementation consequences

- Use CLIProxyAPI Management API v8 for administration; keep its management credential server-side.
- Keep CPAMP Full Mode as the sole consumer of CLIProxyAPI usage events and read CPAMP durable history through an adapter.
- Map ProxyLens-issued client keys to Keycloak groups/applications for authorization and usage attribution.
- Export redacted, user/session-attributed generation telemetry to Langfuse asynchronously.
- Use Docker Compose with persistent volumes, healthchecks, private networks, and Compose secrets.

### Validation performed

Reviewed official CLIProxyAPI and CPA-Manager-Plus repositories/docs/source, Langfuse self-hosting/token-cost/OTLP docs, and Docker Compose services/secrets docs. Findings are recorded in `docs/research/proxy-stack-research.md`.

## 2026-10-23 — Revised architecture: CPAMP Full Mode plus narrow ProxyLens integration

### Scope

Refined the architecture after comparing custom usage management, LiteLLM, CPA-Manager-Plus Lightweight Panel, and CPA-Manager-Plus Full Mode against the requirements for subscription-to-API access, CPAMP-like usage statistics, user management, Langfuse observability, and Docker Compose deployment.

### Decision

Use CPA-Manager-Plus Full Mode instead of rebuilding the global usage ledger and analytics layer. Keep CLIProxyAPI as the provider/OAuth gateway. Add only a narrow ProxyLens integration boundary for user/API-key identity, authorization, user-scoped usage access, and Langfuse attribution/export.

### Rationale

- CPAMP Lightweight Panel replaces the CLIProxyAPI UI but does not provide persistent monitoring or analytics.
- CPAMP Full Mode already provides SQLite-backed request history, token and latency analytics, estimated cost, filters, request inspection, account health, quota inspection, and usage-derived operations.
- CPAMP is an operator/management panel, not a user-facing multi-tenant API gateway. It does not by itself establish the required user-to-key authorization boundary or private per-user usage views.
- CLIProxyAPI's usage queue is consumptive. CPAMP Full Mode must remain the sole queue consumer for a given CLIProxyAPI instance; competing collectors could split or lose events.
- Langfuse supplies observability and custom dashboards, but it is not the product authorization source or authoritative usage ledger.

### Implementation consequences

- Public model traffic must pass through a ProxyLens-controlled identity/integration boundary before reaching CLIProxyAPI, or use an equivalent existing gateway whose identity can be correlated reliably.
- ProxyLens must not expose CLIProxyAPI Management API credentials or CPAMP manager credentials to end users.
- ProxyLens should read CPAMP's durable history through a supported API/export/read integration. Direct SQLite access is a fallback requiring an explicit compatibility decision.
- ProxyLens must map its authenticated user/application identity to CPAMP request records and Langfuse `userId`, `sessionId`, metadata, and tags.
- Langfuse export must be asynchronous, redacted by default, and resilient to temporary ingestion failures.
- LiteLLM is not a default dependency. Add it only if its gateway features are required and its compatibility with CLIProxyAPI's Responses API, streaming, tool calls, and usage metadata is validated.

### Validation performed

Compared the requirements against the documented CPAMP Lightweight/Full capability split, CLIProxyAPI usage-queue and Management API behavior, Langfuse user/session and token/cost capabilities, and Docker Compose deployment primitives. Detailed evidence and source URLs remain in `docs/research/proxy-stack-research.md`.

### Follow-up work

1. Verify the CPAMP Full Mode read/export surface for request history and filtering.
2. Confirm the exact CLIProxyAPI request identity fields available to CPAMP and the correlation strategy.
3. Build a Compose proof of concept with Keycloak, one CLIProxyAPI provider account, CPAMP Full Mode, ProxyLens, Langfuse, and a redacted usage export path.

## 2026-10-23 — Finalized pre-spec architecture contracts

### Scope

Resolved the architecture and domain decisions required before implementation specs.

### Decisions

- Keycloak is the sole source of truth for human identities, authentication, groups, memberships, and group administration. Phase 1 uses one self-hosted `proxylens` realm with flat groups and no external-Keycloak integration.
- ProxyLens applications and client keys belong to exactly one Keycloak group. Users may belong to multiple groups; access is the union of their permitted group scopes.
- CLIProxyAPI remains the provider/OAuth and protocol boundary. Phase 1 targets Codex OAuth and the required OpenAI Responses-compatible streaming, tools, and multimodal path.
- CPAMP Full Mode is the sole CLIProxyAPI usage-queue consumer and authoritative durable request-history/analytics service. ProxyLens maintains only a rebuildable usage projection.
- ProxyLens uses a supported CPAMP read/export interface first and a version-pinned read-only SQLite fallback only when explicitly enabled. ProxyLens never consumes the CLIProxyAPI queue directly.
- ProxyLens authorization, rate limits, model/provider allowlists, request identity, client-key lifecycle, audit records, usage projections, and asynchronous redacted Langfuse export are in scope. Hard token/cost budgets are deferred until usage freshness and correlation are proven.
- Docker Compose is the single-host reference deployment. High availability, multi-host scaling, multiple CPA/CPAMP connections, nested groups, external Keycloak, and raw prompt/output retention are out of scope for Phase 1.

### Validation gates

The POC must verify CPAMP read/export, request-ID correlation through CPAMP, usage projection freshness within 60 seconds under normal operation, Keycloak OIDC and role mapping, Codex OAuth/streaming/tool forwarding, redacted non-blocking Langfuse export, and restart/dependency-outage behavior.

## 2026-10-24 — Issue #2: Compose and Python service foundation

### Scope and base

Implemented on `impl/issue-2-compose`, based on `integration/phase-1-poc` at
`3fc4aef`. Adds one runnable Compose stack, Python 3.12 FastAPI/httpx/psycopg
entrypoints (`python -m proxylens api|gateway|worker`), configuration tests, and
deployment/maintenance documentation. This is the foundation ticket, not parent
#1's completed identity/provider/usage POC.

### Decisions and rationale

- Digest-pin upstream Python 3.12.15, PostgreSQL 17.11, Keycloak 26.8.1,
  CLIProxyAPI v8.0.40, and CPAMP v1.14.9. Verified official tags, build workflows,
  configuration source, and registry manifests; record evidence in
  `docs/dependency-pins.md`. Python dependency closures are hash-locked separately
  for runtime and development. The local app image is tied to the deployment's
  recorded Git commit and built image ID.
- Separate PostgreSQL service/volume/credential for Keycloak so identity storage
  stays owned by Keycloak; ProxyLens PostgreSQL is its future resource/projection
  store. No local authoritative identity schema is introduced.
- Compose secrets are mounted only to their consumers. Keycloak's wrapper reads
  files and exports values within its process environment, because it lacks a
  generic file-secret option. The realm import uses environment placeholders.
  `secrets/` is ignored, directory mode 0700, files 0644 for nonroot container
  readability through local file-backed mounts. Secret contents never enter
  Compose interpolation or the image build context.
- CPA needs writable configuration (including startup hashing and management
  writes). A networkless initializer atomically seeds a persistent config volume
  from mounted secrets only when absent. Existing config is preserved, including
  upstream rewrites from JSON to YAML. OAuth state has its own persistent volume.
  Rotation is explicit and coordinated, not an implicit overwrite at startup.
- CPAMP Full Mode alone receives the management key at runtime and consumes CPA
  usage via its `http` collector. Runtime logs confirmed v1.14.9 uses CPA's legacy
  `/v0/management/usage-queue` compatibility route. ProxyLens has no usage-queue
  implementation. Its worker receives a CPAMP manager key only for future durable
  history integration; it currently runs only a private health server.
- Publish only loopback gateway 8000, operator API 8001, and Keycloak 8080. CPA,
  CPAMP, databases, worker, and Keycloak management health remain unbound on the
  host. Internal backend/identity/provider networks separate paths; separate
  edge/egress networks provide required ingress and provider/metadata connectivity.
- Use parent #1's existing-local-Langfuse option. Configuration and mounted real
  project-key slots are present; no fake receiver, embedded Langfuse stack, export,
  or delivery claim. Empty endpoint/keys mean unconfigured. Later exporter work
  must validate the real endpoint and its independently backed-up state.

### Important behavior rules

- `/health/live` reports process availability; `/health/ready` performs bounded,
  parallel dependency probes and a real PostgreSQL `SELECT 1`. Failures return
  503 with fixed dependency labels, never exception details/secrets.
- API depends on PostgreSQL and Keycloak discovery; gateway also checks CPA;
  worker checks PostgreSQL and CPAMP. CPAMP/Langfuse are not gateway readiness
  dependencies. Health does not implement request authorization.
- No business routes or forwarding are exposed; they return 404. Later tickets
  own JWT/role/group validation, client keys, database schema, request forwarding,
  CPAMP reads/correlation, usage freshness, and Langfuse jobs.
- Long-form startup dependency conditions wait for health or initializer success.
  Compose does not stop/restart a merely unhealthy dependent after startup.
- CPA's usage queue remains volatile, with 3600-second retention configured.
  CPAMP downtime/CPA restart may lose uncollected data; no recovery guarantee or
  tenant usage completeness is implied. Healthchecks never pop the queue.
- Realm/config/bootstrap secrets initialize persistent state once. Changing files
  alone does not rotate persisted database, Keycloak, CPA, or CPAMP credentials.

### Validation performed

- TDD tracer slices: configuration/management isolation test failed before Compose
  existed; repeatable secret/config bootstrap test failed before scripts existed;
  public health contract tests failed before the application existed. Each passed
  after its implementation. Additional config guards verify pins, state mounts,
  bind-source existence, dependency conditions, and mounted-secret grants; negative
  bootstrap cases verify absent/empty management keys never create an open config.
- All 8 local Python 3.12 tests passed, along with Ruff lint/format checks, Bash
  syntax checks, hash-locked installation, and official standalone Compose v5.6.1
  `config --quiet` validation.
- **Docker Engine is absent.** Supplemental runtime validation used rootless
  Podman and the official Compose CLI through Podman's Docker-compatible socket,
  isolated project `proxylens-issue2-smoke`, loopback ports 28000/28001/28080.
  Built the application Dockerfile; pulled digest-pinned upstream images; initial
  full-stack `up --wait` reached healthy state for every long-running service.
- Verified API/gateway ready=200, real realm discovery and configured issuer,
  worker health command, and empty host port bindings for CPA/CPAMP. CPA logs
  showed CPAMP HTTP queue polling, establishing actual connection bootstrap.
- Rebuilt the final app image and recreated the stack successfully; all services
  returned healthy. CPA initializer explicitly preserved its existing config,
  and Keycloak's persisted realm remained discoverable. Integration-tip merge
  was already up to date at `3fc4aef`.
- Stopped/restarted PostgreSQL, Keycloak, and CPA independently: expected readiness
  failure and recovery occurred. Stopping CPAMP left API/gateway ready and worker
  unavailable; restarting recovered the worker. An immediate post-restart sample
  transiently returned gateway 503; the settled check matched the dependency table.

### Limitations and follow-up discipline

Docker Engine-specific networking, bind-secret behavior, restart semantics, arm64,
fresh-host TLS ingress, and actual backup/restore/upgrade/rollback drills still
require validation. No real provider/OAuth, identity-token acceptance, correlated
usage record, or Langfuse delivery was exercised. CPAMP HTTP health is not proof
of collection freshness or durable-history correlation. Keep those parent #1
acceptance gates open.

Check `compose.yaml`, `Dockerfile`, dependency locks, `deploy/`, `src/proxylens/`,
`tests/`, and both deployment/pin documents together when changing a dependency.
Preserve CPAMP's sole-consumer ownership and explicitly document any new secret
grant, published listener, persistent-state migration, or health contract.

## 2026-10-24 — Issue #3: deterministic request-lineage contract

### Scope and decisions

Based `impl/issue-3-correlation` on integration `d97f7b4`. Added reusable frozen
dataclasses, bounded CPA trace parsing/diagnostic propagation, exact-match
correlation, redacted observation metadata, PostgreSQL repository and migration
`003_lineage.sql`. Interfaces/lifecycle are in `docs/correlation.md`.

Use gateway-generated UUIDv4 ingress IDs and reverse-map only the returned CPA
v8.0.40 full UUIDv7. Incoming IDs, timestamps, shared credentials and provider
Responses object IDs cannot establish ownership. Preserve CPAMP v1.14.9
`(instance, event_hash)` identities one-to-many for retries. Missing/partial,
correlated, duplicate and ambiguous are distinct. Structural correlation does
not certify deployed compatibility.

Retain all competing native-ID claims. A live SQL resolution view removes
ownership from earlier events when a later collision appears, including two
requests from the same owner. Conflicting replay of one CPAMP hash is sticky
ambiguous. Duplicate reads are not second countable attributions. No broader
resource/identity tables, raw content or credentials are stored by this module.

### Validation and integration boundaries

Test-first slices failed before parser, ingress generation, correlation,
PostgreSQL persistence and metadata/gate implementation. Tests exercise production
SQL in unique schemas on the coordinator's disposable PostgreSQL, including
reconnection, concurrent connections, late collisions, rollback, replays and
secrets/unsafe-value rejection. Full suite: **41 passed** (33 new contract/repository
cases, including 9 real PostgreSQL cases); Ruff lint, changed-file format checks
and `git diff --check` passed. No provider or Langfuse delivery is simulated as proof.

#7 must commit resolved ingress ownership before dispatch, bind returned headers
immediately, and own transport/protocol outcomes without replaying provider work
to repair telemetry. #10 must query current resolution for scoped publication,
not trust cached owner columns; it owns projection/cursor transaction wiring.
#8 consumes only allowlisted IDs/status metadata. Migration/startup orchestration,
resource foreign keys and full gateway/projection lifecycle wiring remain those
tickets' responsibilities. Retention must preserve ambiguity/dedup evidence for
the whole projected-history lifetime.

### Blocker / proof gate

`docs/evidence/issue-3-correlation.json` explicitly records no live samples.
Authorized Codex execution → returned CPA header → actual CPAMP collector
persistence remains unproven; no provider OAuth was configured by this workflow.
The pinned-source and synthetic-history evidence lives in
`/data/tmp/opencode/proxylens-phase1/contracts.md`. Tenant usage remains hard-gated
off even if a caller supplies a durable-history proof flag. Enablement requires
an evidence-reviewed change, both #3/#4 gates, and the real scenarios listed in
the artifact. Distinct application credentials are only a possible coarse-owner
fallback, not request-level proof; no irreversible fallback/ADR selected.

## 2026-10-24 — Issue #4: pinned CPAMP durable HTTP adapter

### Scope and decisions

- Based `impl/issue-4-cpamp` on `integration/phase-1-poc` at `d97f7b4`.
- Added async httpx read-only CPAMP v1.14.9 adapter. Analytics POST provides fixed
  filtered windows with both keyset cursor fields; JSONL export stages a retained
  snapshot candidate. Optional status reads diagnose collector faults. Supported
  HTTP exists, so no SQLite fallback or queue implementation is needed.
- `(configured stable CPAMP instance ID, event_hash)` owns deduplication identity.
  Native request IDs can repeat across attempts. HTTP omits internal row IDs,
  execution IDs, original queue JSON/canonical accounting, and exact row cost.
  Preserve omissions rather than deriving IDs from cursors or inventing zero cost.
- Source-specific raw numeric/token metadata allowlists are separate from versioned
  exclusive Codex buckets. Unsupported/missing evidence stays unknown; negative,
  conflicting and inconsistent accounting stays inconsistent. Never add reasoning
  to inclusive output or duplicate raw cached/read counts.
- Bound pages, rows, bodies, JSONL lines and whole-read time. Validate schema,
  ordering, cursor progress, duplicates, conflicting identities and retention
  coverage. Keep last clean analytics result on failure/degradation; expose
  available/stale/degraded/unavailable with fixed redacted reason codes.
- HTTP export has no completeness footer and can end as a valid prefix after a
  server-side failure. It always remains an unverified/degraded rebuild candidate;
  no destructive projection replacement or tenant proof follows from EOF.

### Validation performed

- TDD at public adapter HTTP/result seams: release-derived fixtures, pagination,
  filters, redaction, token uncertainty, malformed/schema/auth/outage cases,
  duplicate/conflict handling, retention and bounded export traversal.
- Final local checks: all 75 repository tests passed (67 CPAMP cases), Ruff lint
  and formatting passed for owned Python files, `git diff --check` passed. Fixtures
  compared equal to captured release response JSON values. Deadline/cancellation
  checks verify stalled streams close; source review corrected contradictory
  `separate_from_input`/`read_included_creation_separate` cache-mode handling.
- `scripts/cpamp-read-poc.py` exercised the actual official Linux amd64 release
  (archive SHA-256 verified), new loopback-only CPAMP data/config, synthetic imports,
  production adapter reads, restart persistence, outage, and real archive/verify/
  delete retention handling. Three equal-timestamp events paginated correctly;
  two share native request ID. Export/raw cache differences normalized to total
  140; auth failed closed, duplicate import skipped all three. Deleted raw history
  became `degraded/retention_gap`; export then returned zero retained rows without
  claiming completeness. Collector stayed stopped; no CPA/provider configured.
- Portable evidence summary: `docs/evidence/cpamp-v1.14.9.json`; full synthetic run
  output: `/data/tmp/opencode/proxylens-phase1/http-proof/adapter-results.json`.
  Evidence host clock is October 23 UTC; session/document date is October 24.

### Contracts and follow-up

`docs/cpamp-contract.md` records source SHA/coordinates, public interface, limits,
freshness/retention/error rules, normalization provenance and reproduction. Own
files: `src/proxylens/cpamp.py`, `tests/test_cpamp.py`, CPAMP fixtures, POC script and
contract/evidence docs. Shared app/config untouched. Projection consumers must
persist identity-based upserts, use overlap/reconciliation, preserve unknowns,
sample collector health and independently enforce tenant proof gates. Live provider
correlation, complete queue delivery and original canonical CPA usage remain
unproven; HTTP access alone does not close parent #1's live acceptance gate.

## 2026-10-24 — Issue #5: Keycloak identity and stable group scope

### Scope and decisions

Implemented on `impl/issue-5-keycloak`, confirmed based on integration
`d97f7b4`. Read issue #5 through `gh --json`, the architecture ADR/glossary,
and independently researched phase-1 contracts/acceptance matrix. This ticket
owns app/config identity wiring, the Keycloak image/realm and dependency locks.

- Separate public browser S256-PKCE, bearer-only API audience/roles, and
  confidential read-only Admin clients. Existing `keycloak_client_secret` file
  is now exclusively the Admin service-account credential. API and resources
  worker receive it; browser/gateway never do. No local identity CRUD or
  membership/cache authority.
- Built-in group mapper emits names/paths, so a small Java protocol mapper
  emits actual stable group UUIDs and signed flatness evidence. Compile against
  JARs from the exact digest-pinned Keycloak 26.8.1 image, with digest-pinned
  JDK compiler; no Maven dependency resolution. Nested children **and parents
  containing children** produce flat=false/empty IDs and are denied. IDs are
  independent of display names. SPI version compatibility is intentional.
- Explicit subject mapper with minimal browser client scopes: the first live
  login exposed that removing default client scopes also removed access-token
  `sub`. Added `oidc-sub-mapper`; final fresh realm import/browser login passed.
- Public interface `identity.py`: immutable verified Principal, Capability,
  GroupAuthority/GroupEvidence, get_principal/get_group_authority dependencies,
  and require_group. Role grants and scope are checked independently. Roles
  from other clients never grant ProxyLens capability. Auditor alone is read-only;
  group-admin applies to every claimed group (documented phase-1 limitation).
- Browser auth validates single-use state/browser binding, code verifier, issuer,
  ID/access signatures/audiences, nonce, subject binding, authorized party and
  optional at_hash. Opaque HttpOnly session stores JWT/CSRF only; every request
  revalidates. Unsafe cookie requests require exact Origin and CSRF. Single API
  process, bounded in-memory sessions; restart requires login. No refresh-token
  persistence; no membership snapshot in sessions.
- PyJWT[crypto] 2.15.1 verified available from PyPI, installed and hash-locked.
  RS256 fixed, typed native UUID subjects/groups, issuer/audience/azp, integer
  exp/iat/optional nbf, typed API roles, 300-second max token lifetime. Strict exp
  boundary; default five-second skew applies to future iat/nbf only.
- Default/max JWKS TTL 300 seconds, serialized refresh at most every 15 seconds,
  including unknown-kid/failure paths. Known cached signing keys plus unexpired
  JWT permit READ while Keycloak is unavailable; no stale-key grace. New login,
  callback and unsafe API requests require reachable group authority. Scope-specific
  USE/MANAGE additionally require live target-group lookup.
- Read-only Admin group existence lookup distinguishes authoritative 404 from
  transport/auth/schema failure. `reconcile(ids, async mark_unusable(evidence))`
  provides resource-worker integration; it never auto-reassigns or repairs IDs.
  **Resource orphan persistence/scheduling/audit remains the resources worker's
  responsibility**, not a new local group table. Missing/nested groups block live
  use/write checks now. Existing orphan flags must also gate resource consumers.
- API readiness includes live group-authority permission check. Bounded local
  token-read availability remains independent from readiness routing.

### Validation performed

- TDD: signed-principal tracer failed before modules existed; malformed-claim
  cases failed before explicit type/subject checks; Admin reconciliation test
  failed before adapter existed; browser tests failed before routes/wiring;
  invalid endpoint configuration tests failed before startup validation.
- 72 Python tests pass: actual RSA verification, wrong issuer/audience/signature,
  expiry/nbf/skew, missing/malformed claims, unsigned/HS256 rejection, bounded
  unknown-kid refresh/rotation/cache deadline, role/scope/multigroup matrix,
  nonce/state/issuer/subject/exchange failures, session replay/CSRF, actual API
  dependency denial before mutation, live-authority outage and orphan-hook results.
  External HTTP is mocked; crypto, FastAPI routing/dependencies and sessions are
  real. No PostgreSQL identity schema exists to replace with mocked persistence.
- Ruff lint/format, Compose v5.6.1 config validation, diff checks, hash-locked
  dependencies and custom-image build passed. A rebuild on this high-core host
  hit Quarkus parallel ZIP file-descriptor exhaustion; bound build-only JVM
  ActiveProcessorCount=2. Rebuild succeeded without changing runtime CPU policy.
  Application Dockerfile build also passed (`400eadae1c77`). Before completion,
  merged integration tip `d97f7b4` (already up to date); clean working tree.
- **Live disposable rootless Podman + Chromium**: dedicated network
  `proxylens-issue5-network`, fresh PostgreSQL 17.6 Alpine container
  `proxylens-issue5-db`, custom Keycloak image `6f7a9afcc7e1`, loopback 28185,
  API 28186; no user/other-agent containers touched. Final image and final realm
  were retested from a fresh disposable database after removing the first test
  instance. Real browser code+PKCE callback and `/api/me` verified actual access
  subject, API audience/role and both group IDs. Admin service account could read
  group records with the seeded read-only roles.
- Live rename preserved IDs; removing membership changed new-token claims;
  deleting/recreating a name kept old ID missing and invoked orphan hook;
  actual nested membership produced rejected signed flat=false token. Created
  a second real RSA signing provider; both published keys validated real browser
  tokens. Stopping Keycloak preserved warm-key token verification, rejected new
  login/Admin calls and rejected verification after injected cache deadline.
  Unknown-kid rotation timing and expiry boundary were exercised in local tests,
  not by a five-minute wall-clock live wait.
- Sanitized live evidence: `/data/tmp/opencode/proxylens-phase1/issue5-live/`
  `browser-result.json`, `behavior-results.json`; harness scripts beside it.
  They contain no bearer/Admin secrets. Disposable setup secret files are separate
  scratch artifacts and are not committed. Session date is 2026-10-24; container
  UTC log timestamps are 2026-10-23 (timezone boundary).

### Limits and future maintenance

Actual application orphan marking, audit transaction and worker schedule must
connect the hook in #9/#6; those are not claimed tested here. No provider calls,
CPAMP correlation, tenant usage or Langfuse behavior is claimed. Docker Engine,
TLS ingress, multiworker sessions, automated existing-realm migration and
per-group role assignments beyond the union model remain outside this check.
Existing issue-2 realms require explicit backed-up client/mapping migration;
import does not overwrite persisted realms. See `docs/identity.md`.

When changing identity, inspect `identity.py`, `keycloak.py`, `oidc.py`, API
lifespan/config, realm/mappers/build and corresponding tests together. Preserve
strict error boundaries, live write checks and no local membership authority.

## 2026-10-24 — Issue #9: durable resources and narrowing policy

### Scope and decisions

Implemented on `impl/issue-9-resources`, based on integration `d97f7b4`. Owns
`db.py`, `resources.py`, `policies.py`, `resource_routes.py`, resource migrations
with prefix 009, tests, and `docs/resources.md`. Identity-owned application,
configuration, packaging and deployment files were not edited.

- PostgreSQL transactions are the durability boundary. Migration startup is
  advisory-lock serialized and checksum verified. Composite application/group
  foreign keys prevent mismatched key ownership; no local users/memberships.
- Keycloak group existence is an async injected authoritative lookup returning
  verified flat-group information. Request claims do not establish existence;
  upstream failure never implies deletion. Identity #5 owns Principal/JWT/role
  validation and group freshness. Resource routes use an injected real dependency
  plus explicit capability/scope adapters rather than implementing JWT again.
- Keys contain 256 random secret bits, with independently generated nonsecret
  prefixes; only SHA256 hashes persist. Issuance reveals plaintext once after
  commit. Rotation revokes the old key with zero overlap and audits atomically.
  Read/authorization connections do not cache revoked/expired key acceptance.
- Explicit model/provider constraints intersect; absent/null is unconstrained at
  that level, empty is deny, no applicable allowlist is deny. Numeric ceilings take
  the minimum. Broader application policies are clipped at use time. Shared
  PostgreSQL rate counters admit application/key budgets atomically in 60-second
  first-request-anchored windows; they are not simultaneous-request semaphores.
- Orphan repair creates a replacement application, revokes old keys, and keeps
  original ownership immutable. Historical request/usage records must never be
  reassigned. Explicit repair/revoke/reconcile events include old/new references.
- Lifecycle mutation/audit failure rolls back together. Authentication denials
  honestly record null identity/scope; scoped audits omit other groups. Database
  outage fails closed with a redacted 503. Gateway must commit its own request
  lineage before dispatch; a committed rate reservation is not automatically
  refunded if subsequent dispatch/lineage fails.

### Validation

TDD red/green slices recorded missing modules/methods and missing rate enforcement,
then exercised production migrations and real transactions against dedicated
PostgreSQL `proxylens_resources` on localhost:55432. Tests cover key persistence,
plaintext absence, policy intersections/updates, expiration, scoped HTTP routes,
orphan reconciliation/repair, outage behavior, audit-constraint rollback, composite
FK mismatch, concurrent rotation and shared rate limits. Independent child Python
processes verify restart durability and committed revocation visibility. Only
external group lookup and verified-principal seams are stubbed.

All 24 repository tests passed (16 resource/route cases plus 8 foundation cases),
including subprocess restart validation. Resource-file Ruff lint/format and
`git diff --check` passed. The real PostgreSQL audit constraint failpoint proved
that a failed rotation preserves the original usable key and writes no partial
replacement/audit. This is local persistence/control-plane evidence, not a live
Keycloak or provider acceptance claim.

### Integration follow-up

`docs/resources.md` freezes gateway methods, fields, errors, policy semantics,
rates, and API routes. Coordinator summary is in the shared phase-1
`resources-contract.md`. At implementation time identity #5 had not merged;
coordinator must run migrations on startup and install the router using #5's
actual Principal dependency, role map and Keycloak group adapter. Joint signed-JWT
API tests and live Keycloak evidence remain integration gates. No app wiring or
live provider/identity proof is claimed by the dependency-injection tests.

## 2026-10-26 — Issue #6 independent operations tranche

### Scope and decisions

Started clean at integration `9113a97` on `impl/issue-6-operations`. Owns
`docs/operations.md`, `scripts/{recovery,ci-tests}.py`, `.github/workflows/ci.yml`,
`operations.py`, `operations_health.py`, migration `006_operations.sql` and tests.
Runtime app/config/Compose wiring is reserved for coordinator continuation after
#7/#10/#8. No neighboring worktrees inspected or edited.

- Separate configurable lifetimes: request/projection/outbox 90 days, audit 365,
  remote observations 90. Strict UTC `< cutoff`; equality retained. Shared writer
  advisory lock and durable monotonic floors prevent expired-source resurrection
  when import/export integrate the helper. Increasing retention cannot recreate
  data already pruned by a prior floor.
- Retention requires explicit gateway/projection/outbox participants; no default
  destructive scheduler. Participant prune, holds, floor update, lineage cleanup
  and deletion audit share one PostgreSQL transaction. Audit failure rolls back all.
- Retained native-ID collision components preserve every conflicting owner: pruning
  one expired owner must never give its surviving peer false attribution. Pending
  work holds have no implicit time expiry; participant retirement must release them.
  Existing lineage event timestamps are first-seen time, so local source-identity
  cleanup is conservative; final CPAMP projection admission uses original event time.
- Typed health consumes existing probes/adapter status, reports independent
  dependency/projection/export states, and discards arbitrary error strings.
  Current CPAMP status cannot prove dropped-event counts/queue coverage; output is
  explicitly unknown. No CPA usage-queue access or automatic upstream deletion.
- Recovery tools require new directories/databases/volumes, preserve current state,
  reject symlink/traversal paths, verify checksums, use 0700/0600 outputs, and never
  print subprocess/server exception details. Credentials enter via private files;
  process arguments never carry their values. Matching recovery-set label, source
  commit/pins/locks and explicit external-store scope accompany each backup.
- Logical PostgreSQL dump and row fingerprints share one exported snapshot; restore
  is transactional into a newly created database with matching-major tools. Cold
  foundation backup uses read-only host source mounts, whole-volume archives, a
  digest-pinned helper and stopped-writer checks. Restore uses new labeled empty
  volumes and never starts services. Secret/config, CPAMP encryption key, and
  external Langfuse stores remain a coordinated operator responsibility.
- OSS Langfuse runbook uses actual v2 observations plus trace DELETE and separate
  blob lifecycle; no Enterprise-only setting advertised as OSS enforcement. Remote
  deletion is not executed by these scripts. Earlier successful foundation restore
  and Langfuse live experiments are acknowledged with their actual limitations.
- CI runs hashed locked install, Ruff lint/format, Compose config and real PostgreSQL
  tests. It creates isolated DBs and fails on any skipped test. No credentialed CI
  service: ephemeral loopback PostgreSQL trust is restricted to the disposable runner.

### Validation performed

TDD red/green at agreed acceptance-matrix seams: absent operations/health/recovery
modules first; then real PostgreSQL exact cutoff, persisted floors/restart,
pending holds, collision ownership, audit rollback and health outage/unknown tests.
Recovery tests reject existing/symlink destinations, public/tampered archives and
archive traversal; populated real PostgreSQL restore checks resources/key
authorization/policies/audit/lineage and every table fingerprint. Only synthetic
group authority is injected; transactions and database utilities are real.

Full independent-base suite passed **201 tests, zero skips** before the additional
source-identity cutoff case. The updated suite is rerun after integration merge.
Ruff lint and Compose config passed; original CPAMP docs fenced-code format failure
is assigned to gateway integration and intentionally not edited here.

Synthetic five-volume cold backup/restore also exercised the actual script through
rootless Podman, digest-pinned PostgreSQL 17.11 helper, fresh volumes only. Fixture
contents and secret copy preserved; existing-volume restore refused; all ten owned
volumes removed. Evidence is private scratch `issue6-cold-f2aa5207/evidence.json`.
This tests archive mechanics, not a new live full-stack restore. Two preliminary
helpers failed safely on local tag lookup/Podman `--mount volume-nocopy` syntax;
digest-only image lookup and portable `-v ...:nocopy` resolved both. No user service
or provider/OAuth credential was touched. Tests' real connection values stay scratch.

### Historical integration hook checklist (same issue #6)

The original checklist was completed by the coordinator continuation in `277e0ce`
and its correction pass: central retention/cadence settings, production migration
startup, projection admission and pruning floors, gateway/outbox holds, completion
scanning, health snapshots, redacted worker audit, and worker lifecycle wiring are
integrated. The locked suite provisions isolated databases and exercises populated
recovery. Live provider correlation and durable-history evidence, remote retention,
and final full-stack outage/restart drills remain acceptance gates; tenant-scoped
usage stays disabled.

### Integration-tip validation

Committed independent tranche `fcc7476`; merged integration `9aa9d48` (gateway #7
and projection #10) as `bf6700c`, preserving both development-note additions. CI
now provisions their DSN variables too. Gateway's fixture parses PostgreSQL URLs,
so CI emits escaped URLs rather than libpq keyword DSNs; ephemeral trust CI gets a
random nonempty unused password for the mounted-file contract. The first merged
run exposed that URL mismatch and one previously observed resource concurrent-rate
storage error. After correcting the harness, the complete suite passed **258 tests,
zero skipped** in 38.84s. Ruff lint/format (64 files), Compose config and diff checks
passed. Current PostgreSQL recovery test also restores the newly merged schemas,
but only resources/lineage have populated recovery fixtures; final populated
projection/exporter recovery still requires the continuation. No app/config/Compose
runtime edits were authored by this tranche.

Exporter integration `c19e5a3` arrived during final tip synchronization and was
merged as `2e879b8`. Added its isolated CI DSN; full suite now **300 passed, zero
skipped** in 44.02s, including repeated real populated PostgreSQL backup/restore
into new databases. Independent phase is complete with all three dependency tips
present; the concrete runtime/retention/health hooks above remain for coordinator
continuation, rather than being silently enabled during this merge.

## 2026-10-26 — Issue #10: CPAMP-derived usage projection

### Scope and decisions

Implemented on `impl/issue-10-projection`, integration base `9113a97`. Owns
`projection.py`, `projection_settings.py`, `projection_routes.py`, migration
`010_projection.sql`, projection tests and `docs/projection.md`. Coordinator owns
application/configuration/Compose startup wiring.

- Rebuildable PostgreSQL facts derive only from the pinned CPAMP adapter. Distinct
  event hashes survive even when native IDs coincide. Raw HTTP-surfaced tokens,
  versioned exclusive normalization, requested/resolved models, null cost and
  available safe native identifiers stay distinct; no raw content or secrets.
- Fixed overlapping windows (30-second target/5-minute overlap) plus hourly
  retained-history reconciliation discover late imports. All windows stage before
  one atomic records/lineage/checkpoint commit. Advisory locking excludes concurrent
  workers. Failed windows or promotion retain last valid data; restart replays safely.
- Analytics/JSONL EOF cannot prove a complete snapshot. Reconciliation upserts;
  it never infers source deletion. Missing retained records degrade explicitly.
  Unverified export cannot replace anything. Local 90-day retention alone deletes
  expired projection rows, strictly before the UTC millisecond cutoff.
- Every tenant/export join resolves current lineage, invalidating prior attribution
  after late collisions. Group/application state is read live from resource tables;
  orphan repair never reassigns historical ownership. No group guessing.
- Tenant routes require the real identity dependency, READ capability plus scope,
  matching persisted deployment binding and both reviewed live evidence artifacts.
  Evidence digests/pins/instances/scenarios must match. Defaults are disabled;
  synthetic proof is temporary test input only, never a deployment enable flag.
- Missing records, unknown normalization/cost and unknown completeness remain null
  or explicitly observed-only. Health distinguishes unavailable/stale/degraded/
  available; successful polling cannot hide old window ends, unmatched native-bound
  requests or historical retention gaps. Tenant health omits global source counts.

### Validation performed

TDD red/green slices exercised production migrations on disposable real PostgreSQL
17.6 (`proxylens_projection`, localhost:55432), per-test isolated schemas. External
CPAMP/JWKS HTTP only is mocked; real JWT signature checks, repository transactions,
concurrent-worker locking, cancellation, restart/reconnection, trigger-injected
commit rollback, replay/keyset pagination, late imports, source corrections,
rebuild equivalence/failure, stale boundaries, gaps, collision poisoning, scope,
orphan repair and fail-closed proof checks are covered.

Python 3.12.13 with locked requirements: 15 projection/route tests passed; full
repository suite: 203 passed against the dedicated PostgreSQL database. Projection
Ruff lint/format and `git diff --check` pass. No provider/OAuth/live CPAMP correlation evidence
was created or claimed; the production gates remain blocked.

Post-commit integration merge: gateway tip `92b7128` merged as `39b1d43`; full
merged suite **244 passed**. First run had a transient gateway concurrent-rate test
503 versus expected 429 (243 passed); isolated rerun and subsequent full suite
passed. No gateway code was changed for that failure. Projection tests stayed green.

### Integration and follow-up discipline

`docs/projection.md` documents schema, exporter-safe current joins, API helper,
worker lifecycle, migration helper, proof review and exact completeness limits.
API startup must install `install_projection_routes`; worker startup must own
`projection_worker_lifespan`; run migrations before both. #8 must re-resolve lineage
before one finalized generation and respect proof/unknown fields. #6 must coordinate
lineage/exporter retention, outage cleanup and health wrapping. Keep staging private
and collision evidence for at least the entire dependent projected-history lifetime.

## 2026-10-26 — Issue #8: immutable metadata-only Langfuse outbox

### Scope and decisions

Based `impl/issue-8-langfuse` on integration `9113a97`; read issue #8, merged
correlation interfaces and coordinated contract/live reports. Own modules/settings,
PostgreSQL migration `008_exporter.sql`, tests, exporter documentation and synthetic
live proof script. Gateway/shared app/config/Compose are owned by other tickets.

- One finalized root generation per persisted ingress trace/generation ID. Live
  v4.69.0 same-ID enrichment duplicates visible observations; therefore no early
  generation/update or optimistic sink deduplication claim.
- Typed allowlist serializes only trusted ownership/native IDs, verified principal
  subject, safe session, gateway status/time/model/provider, proof-gated exclusive
  usage and explicitly classified cost. Unknown cost stays absent; possible sink
  inference is labeled estimated/not billing. No content-capture or raw-error field.
- Immutable payload bytes at first committed attempt. Before attempt, enrichment
  uses row-lock serialization; later change records a sticky stale flag/hash only.
  Default proof-disabled input finalizes gateway-only `usage_unproven`; future
  proof-enabled incomplete inputs have a bounded explicit partial-finalization wait.
- Durable fenced leases, SKIP LOCKED claims, bounded rows/payload bytes/response/
  attempts/request age/backoff. Admission uses one advisory lock and aggregate spool
  accounting (Phase 1 O(N) tradeoff). Retain terminal dedup rows through local retention;
  reject expired original requests even after pruning. Source scans must remain
  retryable after capacity suppression; aggregate rejection counters are durable.
- HTTP/JSON v4 with bounded credential-file reads and Basic auth. Actual 200 queue-job
  objects accepted; strict partial-success parsing, no response text persisted.
  Established connection failure retries; 429 requires explicit pre-admission trust.
  Timeout/disconnect/5xx/408/malformed success/expired lease are UNCERTAIN, never an
  automatic resend. No credential redirects/environment proxies or provider replay.

### Validation and integration limits

TDD public seams: typed snapshots, real PostgreSQL outbox/leases, external HTTP,
worker drain and actual v2 readback. Red phases preceded serialization, migrations,
repository lifecycle, transport, worker, retention, pre-send fencing and timezone-
stable identity hashing. Independent interpreters verify durable pending claims and
abandoned-attempt recovery. Native cache-write tokens remain a separate exclusive
bucket, not double-counted inclusive input. All tests use synthetic identities.

Live disposable Langfuse v4.69.0 ingestion/readback on 2026-10-26 passed: genuine
loopback connection refusal followed by fresh repository/transport recovery, one
root generation, original IDs, null input/output, empty supplied usage/cost and
`usage_unproven`. Repeated scan/late enrichment scheduled no second send. Machine
user omission reads back as empty string rather than null, verified and recorded
in the proof harness. Evidence: `docs/evidence/exporter-v4.69.0.json`.
Additional actual-sink fault injection accepted a fresh generation then replaced
only its acknowledgement with malformed JSON. The production worker persisted
`UNCERTAIN/malformed_success`, v2 readback showed exactly one generation, and later
drain did not resend it (`docs/evidence/exporter-v4.69.0-uncertain.json`).

Supported Python 3.12.13 environment installed from hash-locked requirements.
Validation before integration merge: 221 tests passed, 9 lineage tests skipped
without their opt-in DSN; all 9 then passed against isolated schemas in the exporter
test database (230 total). Includes 42 exporter cases. Owned-file Ruff lint/format
and `git diff --check` passed. No new runtime dependency or lock change required.
After committing implementation `310d13a`, merged integration `92b7128` via
`a86e862` (gateway #7 and shared wiring). Full supported-Python suite with the
lineage database gate enabled: **271 passed**, zero skips. Owned-file Ruff lint,
format and diff checks passed after merge. Shared app/config/Compose changes are
inherited from integration, not exporter-owned edits.

Concrete gateway/projection scan orchestration, principal-evidence persistence,
health scheduling and retention wiring are deferred to #6 because #7/#10 lifecycle
tables were developing concurrently. Exact methods and mapping are documented in
`docs/exporter.md`; no claim of integrated provider-response isolation yet.
Uncertain read reconciliation, destination-wide auth pause and remote retention
remain operational follow-up. No provider calls/OAuth, live CPAMP attribution or
native usage fabrication occurred. Local deletion is not remote deletion proof.

## 2026-10-26 — Projection/exporter integration and unified validation

### Scope and merge decisions

Verified clean `integration/phase-1-poc` at gateway merge `92b7128`. Merged
`impl/issue-10-projection` tip `f803f07` with `--no-ff` as `9aa9d48`, then merged
`impl/issue-8-langfuse` tip `1b8efb6` with `--no-ff`. The only conflict was appended
`DEVELOPMENT.md` sections; both implementers' additions were preserved verbatim.
Implementation findings are deferred to the coordinator's single correction pass.

### Validation performed

- Supported Python 3.12.13, pytest 9.1.1, real PostgreSQL 17.6 on the existing
  loopback test instance. Each validation batch created its own uniquely named
  database and dropped it afterward. All five test DSN variables were explicitly
  redirected, including `PROXYLENS_TEST_DATABASE_URL` for the nine lineage tests.
- First unified suite: **285 passed, 1 failed, zero skips**. Failure:
  `tests/test_resources.py::test_concurrent_rate_ceilings_share_postgres_across_repository_instances`.
  Concurrent authorization raised `StorageUnavailable` through `db.py:36` instead
  of returning the expected allowed/rate-limited results.
- In a fresh isolated database, that test alone passed; the following full suite
  repeated the same failure: **285 passed, 1 failed, zero skips**. Root cause and
  correction remain open; this is not a clean unified test result.
- Repository-wide Ruff lint passed; format check passed for all 63 Python files.
  Compose v5.6.1 `--env-file /dev/null -f compose.yaml config --quiet` passed.
  Working/staged whitespace checks and verbatim preservation of both development
  sections passed. No runtime credentials or GitHub access were used.
- Test logs/JUnit/validation metadata are under
  `/data/tmp/opencode/proxylens-phase1/merger-20261026-c1eff389099f/` and
  `/data/tmp/opencode/proxylens-phase1/merger-retry-20261026-13f7b392af84/`.

### Issue #6 coordinator continuation

The coordinator continuation wires `app.py`/`config.py` settings into the API and
worker lifecycles. The API installs proof-gated projection routes. The worker owns
one CPAMP adapter/projection task and one operations supervisor for completion
scans, exporter recovery/drain, retention participants, CPAMP status, and periodic
Keycloak group reconciliation. The worker health response combines bounded
dependency probes with redacted projection/export diagnostics; exporter health does
not gate provider forwarding. Compose gives the worker the CPAMP manager key and
provider-network reachability without granting it CPA management credentials.

The completion scanner uses current proof-gated `projection_resolved` joins,
explicit gateway-outcome mapping, and retains source eligibility after bounded
outbox/storage failures. Existing migrations are discovered at startup; tenant
usage remains disabled pending the reviewed live correlation/history proofs.

### 2026-10-26 correction pass after fixed-point review

The final correction pass made retention admission explicit for old projection
events, fenced exporter recovery/mutation paths with the shared retention floor,
preserved visible terminal exporter outcomes before pruning, released outbox holds
on standalone pruning, validated non-object recovery manifests, persisted final
worker status checkpoints, and removed the integration branch from CI triggers.
The real outbox retention participant now has isolated PostgreSQL coverage. The
post-correction locked suite passed **304 tests, zero skips**; Ruff, formatting,
compilation, and diff checks passed. Docker Compose validation remains unavailable
in this environment because Docker and a Compose provider are absent.

Follow-up review correction: gateway holds now release after a pending lifecycle
row becomes terminal, supervisor checkpoints preserve typed diagnostic state, and
the unrequested CLIProxyAPI commercial-mode change was removed. The locked suite
remains green at **306 tests, zero skips**.

## 2026-10-27 — Final review: CPA raw-content logging guard and local port contract

### Scope and decisions

The final signoff correction restores the pinned CLIProxyAPI v8.0.40
`server.commercial-mode: true` setting in the shipped template. The pinned source
shows that this setting omits the request-body logging middleware; setting
`observability.logs.request-log` to false alone still permits bounded error-path
body capture. Debug logging, file logging, and request logging remain false.

The CPA initializer now treats the persistent `cpa_config` volume as a safety
boundary. First boot writes the safe template and mounted credentials atomically.
Later boots preserve an existing config byte-for-byte only after validating the
four required logging settings. A missing or unsafe setting fails initialization
without overwriting the config or printing credentials; operators must back up
the volume and apply the pinned v8.0.40 config migration before CPA accepts
traffic. OAuth state remains in its separate persistent volume.

The README's local commands now match the reference listeners: gateway 8000,
ProxyLens API 8001, and worker health 8002.

### Validation performed

Added bootstrap coverage for the generated safe template, safe persistent-config
preservation, unsafe legacy-config rejection, and the README/Compose port
contract. Targeted and locked suite results for this correction are recorded in
the final-review handoff artifact.

The final documentation/freshness pass updates the runtime scope and locked-suite
prerequisites in the user-facing guides, propagates projection window staleness
into worker operations health, and makes CPAMP adapter/collector health gate worker
readiness. The same locked suite remains green at **307 tests, zero skips**.

## 2026-10-27 — Remaining Phase 1 live acceptance

### Scope and decisions

The isolated loopback runtime exercised the actual pinned CPA v8.0.40 and CPAMP
v1.14.9 path through ProxyLens using two synthetic Keycloak groups/applications
and the existing single Codex OAuth credential. The harness is
`scripts/live-acceptance.py`; setup/ownership/evidence limits are in
`docs/live-acceptance.md`. It reads CPAMP only through authenticated analytics
HTTP and never accesses the CPA usage queue.

The actual CPA v8 configuration and credential model registry were attested
privately before dispatch: one enabled Codex credential, no configured model
alias or alternate provider route, no credential routing override, zero retry
rounds/bootstrap retries, and no quota model switching. The operator-attested
gateway route was then limited to the exact returned model. No route or proof
gate was guessed from a public model listing.

### Live evidence achieved

Non-streaming, streaming, function-tool, and tiny synthetic image-input requests
returned HTTP 200 with expected Responses behavior. Each preserved first-byte
streaming semantics, produced a full native CPA UUID binding, yielded exactly one
matching CPAMP event hash through the supported analytics read, retained separate
alpha/beta group/application/key ownership, and became visible in about 1.0–1.1
seconds. Repeated CPAMP reads returned the same event hashes. The worker exported
one metadata-only Langfuse generation per case; v2 readback confirmed safe group,
application, ProxyLens/native IDs, no human machine identity, no prompt/output,
and no usage/cost while the proof gate was disabled.

Bounded cancellation returned HTTP 200 and a native binding, then recorded
gateway `cancelled` with no CPAMP durable event. The harness records this as
partial evidence and does not infer usage or ownership from timing/model/key
similarity. A worker restart left readiness unavailable until a durable-history
read was completed; this is now explicit in runtime health and documentation.

The recovery and outage fixtures are synthetic and prove application/storage behavior;
they do not prove provider OAuth validity, real provider request recovery, live CPA-to-
CPAMP correlation, live Langfuse acceptance, remote retention deletion, or a full
operator restore of an external Langfuse deployment. The existing live runtime was
not stopped or modified. Tenant-scoped usage remains disabled until independently
reviewed live correlation and durable-history artifacts exist for the exact deployment
binding.

## 2026-10-27 — Final code-review correction pass

### Scope and decisions

Addressed all actionable findings from the standards/spec review on branch
`fix/phase1-final-review`, based on integration tip `266e7e4` (including the
operations/deployment merge).

- Path usage handlers now pass their `{group_id}` / `{application_id}` values into
  the same authorization/query seam used by query routes. Application IDs are still
  checked against their current resource group and the caller's current Keycloak
  scope; query filters remain query parameters.
- Management `IdentityError` denials are handled at the resource-route boundary and
  recorded with null actor/group/resource when identity was unavailable. Audit write
  failure changes the response to redacted 503 and never permits the operation.
- Gateway authorization denials are recorded through the resource audit repository
  before returning. Only resolved machine-key group/application references are used;
  no request body, key, upstream text, or guessed human actor is recorded.
- Exporter status policy remains conservative for ambiguous outcomes. Bounded durable
  retries cover connection/pool failures and explicitly attested pre-admission 408/5xx
  or pre-send write timeout; bare 408/5xx, read/write ambiguity after body start,
  cancellation, and post-send failures remain `UNCERTAIN`. Scanner-produced
  correlated payloads store a lineage tuple and recheck current resolution at claim
  and immediately before send, invalidating stale ownership after a native collision.
- Worker status checkpoints wrap JSONB details in psycopg `Jsonb`, preserving the
  fixed redacted diagnostic shape.

### Validation performed

TDD regression coverage was added for path scoping, unauthenticated management
audits, gateway denial audit/no-forwarding, real-PostgreSQL JSONB status persistence,
temporary exporter response policy, and late native-ID collision invalidation between
scan and claim.

- The branch already contained integration tip `266e7e4`; no additional merge was
  required. `integration/phase-1-poc` and `fix/phase1-final-review` pointed to the
  same commit before this correction commit.
- The complete isolated locked suite passed **322 tests** in 52.06 seconds using
  `PROXYLENS_CI_DATABASE_URL` against the dedicated PostgreSQL 17.6 service and
  `PROXYLENS_RECOVERY_ENGINE=podman`
  `PROXYLENS_RECOVERY_PG_CONTAINER=proxylens-test-postgres`. This exercised both
  populated recovery tests through the matching PostgreSQL utility container.
- Earlier focused review regressions passed **7 tests**, the broader targeted batch
  passed **104 tests**, and the exporter/runtime batch passed **52 tests**.
- Ruff check passed; Ruff format check passed for all 50 checked Python files;
  `python -m compileall -q src tests` passed; `git diff --check` passed.
- No live service, provider credential, tracker, remote branch, or pull request was
  modified. The exact changed-file list and commit are in the handoff artifact.

### Validation and remaining gates

The new harness reservation seam and redaction failure seam pass, along with the
operations-health regression suite. Ruff passes for the harness/runtime change.
The production proof gate remains disabled: retry/failover attribution,
live native-ID collision behavior, CPAMP outage/restart/retention completeness,
and independently reviewed correlation/history artifacts remain outstanding.
The current worker runtime also demonstrates the conservative post-restart
readiness state until a normal projection read succeeds; no tenant-scoped usage
claim is made.

Private raw evidence and credentials remain under
`/data/tmp/opencode/proxylens-phase1/live-acceptance-20261027/` and are not
copied into the repository.

## 2026-10-27 — Final review correction follow-up

The second final-review correction pass closes the remaining boundedness,
ordering, identity-evidence, readiness, and integration-audit defects.

- CPAMP `_Read` retains bounded sanitized records by event hash before exact
  request filtering. Conflicting copies therefore quarantine both copies in
  either page order; filtered rows cannot hide a conflict and no raw payload is
  retained.
- OIDC callback state is accepted only as 1–256 URL-safe ASCII characters before
  constant-time comparison. Unicode, malformed, and oversized values return the
  fixed 401 identity error while preserving single-use login state.
- JWKS refresh uses `httpx` streaming, rejects redirects/compression, enforces a
  65,536-byte body cap incrementally, and applies a two-second whole-refresh
  deadline while retaining serialized refresh/cooldown behavior.
- Group reconciliation passes the authoritative `GroupEvidence` into the
  resource transaction. Missing groups persist `orphaned`; nested groups persist
  `unusable`; transient authority failures do neither. The state transition and
  redacted `group.reconcile` audit are atomic, with migration `013` adding the
  supported state.
- Proof-disabled worker readiness reads only authenticated CPAMP collector
  status. CPAMP/projection integration transitions now write bounded metadata-only
  audit events transactionally. Gateway model POST behavior remains intentionally
  zero-retry for ambiguous provider admission, including pre-response failures.

Validation completed: the isolated locked suite passed **335 tests** with zero
skips; Ruff check and format check passed; Python compilation and `git diff --check`
passed. The dedicated PostgreSQL databases were created and removed by the locked
suite harness.
## 2026-10-29 — #8 native content-rich tracing and narrow trusted callback seam

Scope: isolated candidate only, active #8 after native tracing/retry revisions;
integration ancestry116821f confirmed and41e9d92 merged. Native configuration
first; installed LiteLLM1.106.6/Langfuse4.15.2/OTel1.45.1 inspected and external
official docs checked. Existing runtime/exporter and shared CPA/Langfuse history
retain their contracts.

Native synthetic serialization demonstrated concrete gaps: native userId
uses caller/customer identity instead of key owner, caller headers/metadata can
override session/user, and credential-like error text is emitted.
Native proxy preparation was also exercised: authenticated owner stamping works,
but trace controls remain. **Correction after full deployed auth smoke:** native
auth already rejects caller destination credentials401 under selected settings;
the preparation-only probe bypassed that earlier gate. No deployed redirect gap
is claimed. Reported exact gap/public seam to
coordinator before implementing the selected minimal callback. OTelv2 also reads
caller trace controls; switching alone does not solve them.

Decision: one `CustomLogger` delegates to fixed `LangFuseLogger` and its native
OTLP construction/batching/delivery. Callback-local copies bind trusted stamped
key owner, labeled deployment/owner request-session fallback, fresh trace IDs and
targeted credential masking while preserving debugging content. No transport,
outbox, inference replay, client modification or cost-normalization code. Owner
identity is analysis, not reader authorization. Missing owner is unattributed;
no raw caller identity fallback. Native error/stream coverage limits remain.

New native OSS organization/project created via native signup/login/UI APIs on
authorized local Langfuse4.69.0. New non-admin OWNER only; A/B have no membership.
Project retentionDays=null, so no automatic deletion selected. Private operator/
project credentials retained0700/0600; setup command verifies exact project and
stages secrets without rotation. #6 owns reader/retention/recovery follow-up.

Validation: TDD public setup seam red (missing command; malformed project payload)
then green8tests. Callback serialized-native seam red (missing module, missing
failure/masking, invalid redacted JSON), green6tests in pinned image/network-none.
Covers A/A2/B, forged controls, canaries, unchanged inputs, native Responses
dispatch and completed-stream tool/image content. Direct native live readback
retained synthetic source/tools/output/timing/cost in new project, no provider
calls. Bypassing dispatcher initially exposed Responses usage0/0; actual native
dispatch converts correctly to80/cache20/output40/total140, without our fix.
Native callback lacks separate reasoning bucket. #7 must verify deployed A5.

Files: `deploy/candidate/{native_langfuse.py,langfuse.compose.yaml,config.yaml,
compose.yaml}`, `scripts/candidate.py`, `tests/{test_candidate_bootstrap.py,
candidate_native_contract.py}`, `.github/workflows/ci.yml`,
`docs/candidate/langfuse.md`. Callback contract CI runs inside exact deployment
image, separate from old-runtime dependencies. Effective capture/spend/error
settings, native queue/retry/truncation limits, project access and reproduction
are documented in the new candidate runbook. No A5/pass or issue completion claim.

Activation completed after commitd52f4b1 and coordinator handoff: only candidate
LiteLLM recreated/mounts relocated issue2→issue8; DB and shared CPA/Langfuse IDs/
start times unchanged. Candidate healthy, native config callback readback exactly
one instance, DB no logging overrides, process log no errors/configured secrets.
Actual native401 caller-destination denial was unattributed;403 A/nonexistent-model
denial read back trusted A/request-fallback and useful error, forged controls/key
absent. No provider dispatch for these denies. #7 released for bounded shared cases.
Recovery of this config must archive the new callback/overlay and disable callback
registration in the **offline copy**; prior no-callback recovery remains historical.

Activation follow-up: corrected all current destination-gap claims and documented
the exact container-only test invocation/CI job, private fixture and evidence
paths. Preserved the preliminary smoke summary (it read the earlier401 before403
ingestion) and verified both final observations separately. Normalized private
probe/source/log artifact modes to0700/0600; runtime key files were already0600.
#7 now owns candidate route/restart/fault coordination during the bounded run;
this follow-up changes documentation only, not live-mounted callback/config.
Validation repeated: six serialized-native seam tests pass in the exact digest
with network disabled; eight bootstrap tests pass; repo-wide Ruff lint/format,
three runbook local links/anchors and `git diff --check` pass. Test review confirms
the hook checks observe native serialized output, input immutability and installed
proxy stamping/dispatch rather than mock the logger or duplicate upstream suites.
Merged integrationb0326db (#7 initial60eb4c4) before final handoff, preserving both
development records. Resolved the shared decisions-table conflict by retaining
#7's bounded A1 evidence and #8's activated setup; shared A5 remains pending.
