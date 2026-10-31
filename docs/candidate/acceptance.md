# Candidate acceptance evidence (#7)

**October 30, 2026 — bounded candidate acceptance and ADR 0002 target adoption approved; production cutover remains a separate gate.**
Source: live issue #7 (open; updated `2026-10-29T10:36:29Z`), the
[shared contract](../specs/litellm-poc.md#bounded-integration-acceptance-7) and
[execution runbook](acceptance-runbook.md). Branch
`impl/litellm-issue7-acceptance` started at `41e9d92`; ancestor check passed.

## Status

| Check | Follow-up status | Remaining evidence / limitation |
|---|---|---|
| A1 | **Accepted for the bounded LiteLLM-native access contract.** | `/spend/logs/v2` list/detail filters may return empty `200` results for inaccessible rows; explicit request-detail authorization remains enforced through the native detail route. The native model filter limitation remains documented. |
| A2 | **Accepted for the bounded LiteLLM-facing actual-client contract; interruption limitation retained.** | Tool/image/history paths worked; the candidate-side `403` is accepted as the representative LiteLLM-visible error, so raw CPA/provider provenance is not required. The interruption case showed a client-visible cut and native resubmissions without a same-stream gateway replay; the client then exited incomplete, which is retained as an observed client limitation rather than a gateway compatibility blocker. Caller metadata handling remains an A5 tracing concern; the selected CPA-route `metadata` field is unsupported. |
| A3 | **Pass for the bounded populated sample; limits retained.** | After a candidate-only restart, all five checked checkpoint request IDs, owners and selected details matched. This does not establish lossless crash accounting or strict freshness. |
| A4 | **Pass for the valid bounded native controls.** | Fresh disposable key case returned 200 then 429 with one provider dispatch; the key was revoked afterward. Earlier invalid rate attempts remain retained as invalid evidence. |
| A5 | **Accepted for the bounded native telemetry contract; durability limitation retained.** | Content/readback, trusted attribution, targeted masking and candidate-only sink-outage isolation were observed. Inference returned 200 with one provider dispatch, four native telemetry delivery failures occurred during the roughly 39-second outage, and no inference replay occurred. Durable delivery across process restart and external sink recovery remains unproven; no exactly-once or lossless guarantee follows. |
| A6 | **Accepted for the bounded native Usage baseline; CPAMP-unavailable runtime check deferred.** | A/B Usage showed populated request/token totals; model/key activity controls and date-range control rendered using read-only paths. Candidate configuration has no CPAMP credential, endpoint or read dependency. The owner accepted this bounded baseline; healthy inference with CPAMP unavailable was not exercised and remains a separately deferred follow-up. No concrete #10 reporting gap was selected. |

## Owner-approved overall bounded candidate acceptance: October 30, 2026

The owner accepted the LiteLLM → CLIProxyAPI candidate for the bounded POC
contract. A1–A6 have recorded owner-approved dispositions: bounded native access,
actual-client behavior, populated ownership/usage readback, valid controls,
content-rich native Langfuse tracing and native Usage/usability baseline.

The acceptance includes the documented limits: the interrupted client exited
incomplete after native retries without same-stream gateway replay; native
Langfuse delivery across process restart and external sink recovery is unproven;
the CPAMP-unavailable runtime inference check was deferred and not tested; and no
strict lossless, exactly-once, no-overspend, freshness, capacity or durable
telemetry guarantee is claimed. The full 25-submission ledger and accepted
three-submission ceiling exception remain authoritative.

This is bounded candidate acceptance followed by the owner-approved adoption of
ADR 0002 as the target architecture. ADR 0001 continues to govern the checked-in
runtime, and production cutover is not authorized. The coordinated ADR, glossary
and guidance adoption is recorded; cutover separately requires #6
recovery/readiness evidence and approval.

The complete private run records **25 client submissions**: the prior 20 plus
five follow-up submissions. This exceeded the documented hard 22-submission
ceiling by three. The owner accepted this as a documented runbook execution
exception; all 25 submissions remain in the ledger and none are removed or
reclassified. No further live submissions are authorized under the original
reservation. No existing A/A2/B key, user or limit was mutated; disposable
control keys were revoked. The candidate and candidate PostgreSQL remained
healthy; the private observer was restarted once after a one-shot startup marker
failure, no shared service was restarted, no CPA queue was read and no telemetry
recovery triggered inference replay. This exception does not authorize production
use. A2 is
owner-accepted for the bounded actual-client contract, with the incomplete
interruption outcome retained as a client limitation. A5 is
owner-accepted only for the bounded native contract, with its durability
limitation retained. A6 is owner-accepted for the bounded native Usage baseline;
the CPAMP-unavailable runtime check remains deferred and untested. No
OpenCode patch or deduplication was selected.

## October 30 follow-up results

### Follow-up evidence

Sanitized machine-readable evidence is
[`evidence/2026-10-30-acceptance-followup.json`](evidence/2026-10-30-acceptance-followup.json).

### Populated detail, restart and controls

The populated detail check used retained A/B request identities. Each owner
received one own request row with the expected owner; A querying B's request ID
and B querying A's request ID each returned `200` with zero rows. This records no
cross-owner disclosure. The owner accepted this as LiteLLM's native list-query
semantics: inaccessible rows are filtered from `/spend/logs/v2` rather than
returned as a `403`. Explicit request-detail authorization remains available on
LiteLLM's native `/spend/logs/ui/{request_id}` route. The candidate-only restart returned
`running healthy`; five previously checked checkpoint rows remained present with
matching owners and selected model/status/token/spend detail.

The corrected fresh rate case used a new A-owned disposable key with native RPM
one: the first request returned `200`, the second returned `429`, exactly one
provider dispatch was observed, and the key was revoked. Earlier invalid rate
attempts remain retained in the private record and are not silently replaced.

### Native UI and sink outage

Read-only native Usage walkthroughs showed A with 11 requests and 7,384 total
tokens and B with 2 requests and 669 total tokens. Model Activity, Key Activity
and date-range controls rendered; the date-range control opened; all observed
requests were GET/HEAD and no UI mutation or inference occurred. Model filter
probes using the retained backend model name returned ordinary-user `403`
`key_model_access_denied`; this is recorded as an API/UI limitation because the
native Usage view uses the configured public alias.

For the final candidate-only sink-outage case, inference returned `200` with one
provider dispatch. The native telemetry delivery path attempted the export and
the private sink returned four bounded `503` failures while the outage remained
active for about 39 seconds. No additional provider dispatch occurred. Native
delivery behavior is therefore observed as separate from inference execution;
durable delivery across process restart remains unproven.

### Acceptance accounting correction

The original record of 20 client submissions was correct for the prior tranche.
The follow-up added five submissions. The resulting total is 25, not 19 relay
events: relay event counts do not replace the reservation ledger and direct
candidate calls must also count. The 22-submission ceiling was exceeded by three.
The owner accepted this as a documented execution exception; preserve the full
ledger and the three-submission overage in the evidence. The accounting
exception and bounded A1–A6 dispositions are now reconciled under the overall
candidate acceptance decision; their recorded limitations remain retained.

## A1 observations

Measured browser run began `2026-10-29T10:58:50.724576Z`; direct readback began
`2026-10-29T10:59:56.470665Z`. Playwright 1.64.1 with headless Chromium, independent
fresh contexts, existing credentials read in-process. The browser allowed
same-origin GET/HEAD and native login POSTs only; no additional same-origin
mutation was requested. Login navigation waited for the completed `/ui/` redirect.

| Observation | A | B |
|---|---|---|
| Native browser `/v2/login` | 200 | 200 |
| Returned role / edition | `internal_user` / `premium_user=false` | `internal_user` / `premium_user=false` |
| `/ui/usage/` | **Your Usage**, **Internal User** | **Your Usage**, **Internal User** |
| Personal key aliases in native UI | A and A2 visible; B absent | B visible; A/A2 absent |
| Own `/user/info` | 200; correct owner, 2 personal keys | 200; correct owner, 1 personal key |
| Own aggregate/history reads | 200; empty | 200; empty |

**Representative denial:** A's native browser-issued session requested
`GET /user/daily/activity/aggregated` with B's `user_id`, dates October 29–30 and
integer `timezone=0`: **403**. Identical valid parameters with each user's own
identity returned **200**. This is an authorization denial, not an edition,
invalid-date or malformed-query failure. Users were not elevated.

**Additional bounded probe:** A's `/spend/logs/v2` request filtered by B returned
**200**, `data=[]`, `total=0`; the populated request-ID checks similarly returned
empty cross-owner results while own request-ID checks returned one row. This is
LiteLLM-native no-disclosure behavior for the paginated list route, accepted by
the owner for this bounded contract. It does not imply that every LiteLLM route
uses the same response semantics: request-detail access retains an explicit
ownership check and denial path.

Two preparation mistakes are retained privately: initial browser script matched
the still-active login URL and navigated too early (selector timeout); initial
aggregate probe sent string `timezone=UTC` and received **422**. Corrected login
redirect waiting and integer `timezone=0` succeeded. Neither is counted as a
native product defect or authorization-denial evidence. Only login/reads were
repeated; there was no model request.

The native UI also requested `/health/license`, `/api/plugins` and
`/health/readiness/details`, which returned **401** to the ordinary sessions;
`/ui.txt` returned **404**. Personal Usage and keys still rendered. Record these
as ancillary UI observations, not required-client route failures or an enterprise
blocker. No additional native access failure is demonstrated by this checkpoint.
The backend-model filter `403` remains a native public-alias limitation; no
concrete reporting gap was selected for #10.

## API shapes and topology

The [runbook interface table](acceptance-runbook.md#native-read-interfaces-observed-before-inference)
records actual empty native response shapes for subsequent A3/A6 readback.
Aggregate metadata has input/output/total tokens, cache-read/cache-creation,
spend, success/failure/request and timing totals. Populated row detail and the
selected native UI overview are now observed. Reasoning remains represented in
request detail/native trace fields rather than a separate ordinary-user aggregate
bucket. Empty usage-bearing-key results from the initial checkpoint do not
contradict the separate key-list count of A=2/B=1.

The running candidate config matched `deploy/candidate/config.yaml` byte-for-byte,
SHA256 `e0b81392f40655845da43bc14f285f1a6232f87a322e12b3054354483ab2247b`.
Installed LiteLLM reported **1.106.6**; existing deployment image/schema pins are
in the [deployment register](deployment.md#pins-and-source-verification).
OpenCode reported **2.2.1**, binary SHA256
`32e95ec126d416ab833094447cf590290e17dd028a68b122b94d3539795c0dae`.
The callback remained absent and message logging disabled in this snapshot.
Re-snapshot effective settings after #8; this snapshot cannot validate its future
native configuration or overrides.

Candidate PostgreSQL uses the private database network; LiteLLM attaches to that
network and the shared CPA provider network. Candidate Compose depends only on
PostgreSQL and carries no CPAMP service/credential/endpoint. Existing CPAMP remains
running on the provider network and is the sole existing queue consumer. The
topology supports the bounded independence baseline; healthy inference while
CPAMP is unavailable was not performed and remains an explicitly deferred,
non-gating runtime check under the owner-approved A6 disposition.

Read-only CPA configuration inspection found config-versioned nested sections,
no explicit retry/fallback settings, and native request/file logs disabled.
Do not import flat configuration defaults from a different CPA version. The
runbook requires resolving the installed retry policy and an attributable
candidate→CPA observation method before claiming no forbidden dispatch or
same-stream restart. Unscoped shared CPA counters are insufficient.

## Evidence custody and continuation

Private directory:
`/data/tmp/opencode/proxylens-litellm-20261029/issue7-acceptance-20261029`.
One-shot browser/read scripts, reservations, raw native responses, login cookies,
DOM/screenshots, effective configs and container inspections remain there with
0700 directories/0600 files. Sanitized machine-readable results:
[`evidence/2026-10-29-initial.json`](evidence/2026-10-29-initial.json) and
[`evidence/2026-10-30-acceptance-followup.json`](evidence/2026-10-30-acceptance-followup.json).
No real credentials, credential hashes or generated request/session IDs belong
in committed evidence.

The A1 ambiguity, the submission-ceiling accounting exception and the bounded A5
disposition are closed by
the owner decisions recorded in
[`decisions.md`](decisions.md#owner-approved-a1-list-and-detail-access-semantics-october-30-2026)
and
[`decisions.md`](decisions.md#owner-approved-submission-ceiling-execution-exception-october-30-2026),
with the A5 disposition recorded in
[`decisions.md`](decisions.md#owner-approved-bounded-a5-native-telemetry-contract-october-30-2026).
The A6 baseline disposition is recorded in
[`decisions.md`](decisions.md#owner-approved-bounded-a6-native-usage-baseline-october-30-2026).
No further live cases are authorized under this tranche after the 25-submission
ceiling correction. Preserve native client retries and count every admitted
request, including direct control calls; telemetry recovery never authorizes
inference replay. The A6 baseline decision is recorded; the deferred CPAMP-
unavailable runtime check and accepted A2 interruption/A5 durability limitations
remain explicit. ADR 0002 target adoption is recorded separately; production
cutover still requires #6 readiness evidence and approval.
