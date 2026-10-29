# Candidate acceptance evidence (#7)

**October 29, 2026 — bounded follow-up evidence; candidate acceptance remains open.**
Source: live issue #7 (open; updated `2026-10-29T10:36:29Z`), the
[shared contract](../specs/litellm-poc.md#bounded-integration-acceptance-7) and
[execution runbook](acceptance-runbook.md). Branch
`impl/litellm-issue7-acceptance` started at `41e9d92`; ancestor check passed.

## Status

| Check | Follow-up status | Remaining evidence / limitation |
|---|---|---|
| A1 | **Partial: bounded access/isolation evidence passed.** | A/B own histories are populated and cross-user aggregate reads return 403. Cross-user `/spend/logs/v2` returns empty 200 rather than a denial, so populated detail isolation remains inconclusive. |
| A2 | **Partial: actual route and OpenCode compatibility observed.** | O-A read/image continuation completed; tools, image and streaming paths worked. E-B was candidate-side 403 before provider dispatch, not proven upstream. X-A recorded client-visible interruption and native resubmissions but ended incomplete. S-A2 exposed downstream CPA-route `metadata` incompatibility. |
| A3 | **Partial: populated ownership and numeric reconciliation.** | A/B totals and retained rows reconcile for the completed interval. No candidate restart/readback was performed, so restart persistence remains pending. |
| A4 | **Partial: revoked-key and model denials passed.** | C-rate is failed/unperformed: the disposable key was revoked before both requests, producing 401/401. No existing A/A2/B key or limit was mutated. |
| A5 | **Partial: native payload/readback, attribution and targeted masking observed.** | Success/tool/result/image/error payloads reached the candidate Langfuse project; forged owner/session controls did not replace trusted key-owner attribution. L-A inference succeeded, but the asynchronous sink-outage rejection was not observed, so outage isolation is inconclusive. |
| A6 | **Partial: candidate topology and populated native Usage observed.** | Candidate has no CPAMP endpoint/credential dependency and healthy inference completed while CPAMP remained the shared queue consumer. Populated UI/filter walkthrough, candidate restart and owner baseline/gap decision remain pending. |

The bounded run admitted 20 client submissions in total: 16 observed through the
candidate relay and four native control calls made directly to the candidate. It
stayed below the hard 22-submission ceiling. No existing A/A2/B key, user or
limit was mutated; one disposable control key was created and revoked. The
candidate, observer and candidate PostgreSQL remained healthy; no shared service
restart, CPA queue read or inference replay was performed. This tranche does not
complete PR #12 or issue #7; readiness/adoption/cutover remain gated. No OpenCode
patch or deduplication was selected.

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
**200**, `data=[]`, `total=0`; B's own history was also empty. This is **inconclusive
for populated-record isolation**, not an observed disclosure or proof of denial.
After S-B exists, use its real retained identity for a representative detail read.
The cache's pinned native source applies owned-row scoping to list queries, but
source inspection does not replace populated execution evidence.

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

## API shapes and topology

The [runbook interface table](acceptance-runbook.md#native-read-interfaces-observed-before-inference)
records actual empty native response shapes for subsequent A3/A6 readback.
Aggregate metadata has input/output/total tokens, cache-read/cache-creation,
spend, success/failure/request and timing totals. Populated row detail and supplied
reasoning retention remain unobserved. Empty usage-bearing-key results do not
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
topology supports the intended independence; healthy inference without a CPAMP
dependency remains unperformed, so A6 is not passed.

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
0700 directories/0600 files. Sanitized machine-readable result:
[`evidence/2026-10-29-initial.json`](evidence/2026-10-29-initial.json).
No real credentials, credential hashes or generated request/session IDs belong
in committed evidence.

Continue on the coordinator's readiness follow-up using the runbook's shared
bounded cases. Coordinate populated history/restart with #6. Preserve native
client retries and count admitted requests; telemetry recovery never authorizes
inference replay. Report any confirmed mapping/access/client defect as a blocker
before expanding custom code. Obtain #1's baseline/gap decision after A6, and
separate authorization for adoption and production cutover.
