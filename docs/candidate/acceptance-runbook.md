# Shared candidate acceptance runbook (#7)

**October 29, 2026 — execution plan and read-only checkpoint.** Follow the
[A1–A6 contract](../specs/litellm-poc.md#bounded-integration-acceptance-7),
[retry boundaries](../specs/litellm-poc.md#retry-boundaries) and
[setup decisions](decisions.md). Results live in [acceptance.md](acceptance.md).
This runbook records bounded candidate acceptance evidence and does not authorize
production cutover.

## Execution boundary and common register

The coordinator must signal **#8 ready** before provider inference, telemetry
delivery, control-fixture changes, fault injection or a candidate restart. Initial
work uses existing A/B browser logins and authenticated reads only. Keep the
running issue #2 mounts intact while #8 coordinates any recreation. Refreshing a
login creates a native UI session; it does not require re-provisioning the fixture.

Use the [deployment register](deployment.md#pins-and-source-verification) once for
image/digest/schema/edition/price provenance. At the actual shared run, privately
snapshot effective mounted configuration, relevant native overrides, container
start times, client version/hash, CPA policy and #8's native destination/mapping.
Record public configuration hashes and settings alongside results. A checked-in
file or earlier startup snapshot does not establish later effective settings.

- Candidate: `http://127.0.0.1:14000`; LiteLLM 1.106.6; OpenCode 2.2.1.
- Alias: `cpa-gpt-5.6-luna`; actual upstream CPA route from deployment register.
- Existing ordinary users A/B, keys A/A2/B, explicit native owner, setup-only admin.
- Private input directory:
  `/data/tmp/opencode/proxylens-litellm-20261029/private`; read `fixture.json` and
  secret files in-process. Never print or source their contents in shell commands.
- Private execution directory:
  `/data/tmp/opencode/proxylens-litellm-20261029/issue7-acceptance-20261029`.
  Directories 0700; scripts, manifests, cookies, screenshots and raw artifacts 0600.
- Commit only case labels, status/counts, numeric usage, fixed synthetic examples,
  config/version fingerprints and limitations. Retain actual request/trace/session
  IDs, credential hashes, headers and all raw bodies privately.

The owner-confirmed TDD seams are public setup, a **selected** conditional telemetry
hook, and recovery commands. If this run exposes custom glue needing a fix, add
one behavioral red → green regression at that seam. Native integration checks
use this runbook/private one-shot scripts; no duplicate upstream CRUD/limit suite.

## A1: native browser login and direct read

1. Use separate fresh Playwright Chromium contexts for A and B. Navigate to
   `/ui/login`, wait for network idle, inspect rendered controls, fill native
   username/password and click **Login**. Wait for the final `/ui/` redirect before
   navigating further; matching `/ui/**` alone also matches the login page.
2. Open `/ui/usage/`; verify **Internal User** and **Your Usage**. Follow the actual
   **Virtual Keys** navigation. Verify A's two known aliases and B's one alias,
   without exposing the other owner's keys. Record native login role and
   `premium_user=false`; use the returned native session for direct reads.
3. Read each owner's aggregate and history with that owner's session. Send the
   same valid aggregate request as A with only `user_id` changed to B. Require an
   authorization denial, not malformed-input rejection. The pinned API's
   `timezone` query field is an integer offset in minutes; use `0` for UTC.
4. Record status/shape and whether personal data is populated. Empty history
   cannot prove populated-row isolation. After sample B exists, reuse its native
   request identity to check detail isolation if the list endpoint only filters
   inaccessible records instead of rejecting the query.

Read-only reproduction in Python, with credentials kept in process:

```python
# session_key comes from this user's native /v2/login response/browser cookie.
# user_id comes from the existing private fixture, never caller ownership claims.
headers = {"Authorization": "Bearer " + session_key}
query = urlencode(
    {"user_id": user_id, "start_date": "2026-10-29", "end_date": "2026-10-30", "timezone": 0}
)
request = Request(base_url + "/user/daily/activity/aggregated?" + query, headers=headers)
# Save the response privately. Emit only status, field names and numeric counts.
```

### Native read interfaces observed before inference

| Interface | Observed shape/use |
|---|---|
| `GET /v2/user/info` | UI's current-owner object; native role, model and limit fields. |
| `GET /user/info?user_id=<own>` | `user_id`, `user_info`, `keys`, `teams`; own personal keys A=2/B=1. Credential/hash-bearing fields remain private. |
| `GET /key/list` | UI uses `keys`, `total_count`, `current_page`, `total_pages`. |
| `GET /user/daily/activity/aggregated` | `results[]`, `metadata`: spend, prompt/completion/total tokens, request success/failure counts, cache-read/cache-creation tokens, timing totals and pagination. Empty results at checkpoint. |
| `GET /user/daily/activity/aggregated/keys` | `api_keys[]`, `total_api_keys`, `offset`, `limit`; usage-bearing keys, empty before inference. |
| `GET /spend/logs/v2` | Required start/end dates; `data[]`, `total`, `page`, `page_size`, `total_pages`, `total_is_capped`. Empty at checkpoint; populated row fields remain to inspect. |

Do not mistake the aggregate's zero defaults for measured zero cache/reasoning use
on a request with missing provider usage. Reasoning was not a top-level aggregate
metadata field in this empty response. Inspect actual populated row/subset fields
after the shared sample; never fabricate a field or a zero to complete A3.

## Bounded shared cases after the readiness signal

Before each case, exclusively create a private reservation with case label,
authenticated key label, expected owner, route, input hash, output bound and cap.
Write `reserved` **before** dispatch; preserve it on timeout/ambiguous outcome.
Record attempts/outcomes afterward. Never automatically rerun a reserved case.
Read-only usage/telemetry readback may be repeated at the bounded times below.

Direct probes use one HTTP submission, no SDK retry loop, 150-second total
deadline and at most 128 requested output tokens. Rate/control probes request
16 output tokens. OpenCode uses private HOME/XDG/state/config, a standalone server,
the native Responses HTTP provider and an explicit title; disable unrelated
maintenance agents/provider discovery as in the retained client preflight. Only
synthetic files/tools are accessible. Preserve native client retries.

The **22-submission reservation ceiling** below is a ceiling, not a target. It
includes possible native retries and two forbidden-control attempts. Per-case
caps and an overall candidate-to-CPA dispatch cap must be observable/enforceable
before live execution. A private transparent relay may count/limit forwarding
while preserving real bodies/Responses SSE; it must not generate successful model
responses, rewrite accounting, deduplicate or retry. Coordinate any candidate
route change with #8 first. A cap-generated error is test machinery, explicitly
labelled; it is not the required upstream-error evidence.

| Case | Key | Maximum client submissions | Shared purpose / synthetic input |
|---|---|---:|---|
| S-A | A | 1 | Nonstream `/v1/responses`; ask for a fixed short reply about `def add(a, b): return a + b`. A2/A3/A5 success and transmitted-code content. |
| S-A2 | A2 | 1 | SSE Responses; fixed short reply plus forged other-owner/user/session/trace/destination metadata selected with #8. A2/A3/A5 owner aggregation and spoof handling. Destination override uses a controlled local sentinel, never an arbitrary external host. |
| S-B | B | 1 | Nonstream fixed reply; independent owner and detail-isolation reference. A1/A3/A5. |
| T-call | A2 | 1 | Force synthetic `fixture_echo` function with one string argument. Record actual native call identity and complete returned tool item. A2/A5. |
| T-result | A2 | 1 | Continue with the actual T-call item and its matching `function_call_output`; synthetic result contains the source snippet. If T-call fails, block continuation rather than invent a call ID. A2/A5. |
| I-B | B | 1 | Tiny generated geometric PNG via `input_image` plus a short question. Record whether image bytes, reference or omitted representation reaches Langfuse. A2/A5. |
| O-A | A | 6 total | Actual OpenCode first turn: read one synthetic source file through its native read tool and return a short answer; second invocation continues the same private session with the synthetic image. Observe tool-result continuation, conversation history and every ancillary route actually used. Six is a shared cap across both invocations and their native retries, not six required requests. A2/A3/A5. |
| E-B | B | 1 | Real route request with a deliberately nonexistent synthetic `previous_response_id` and short input. Count as a representative LiteLLM-visible error when the client receives the documented LiteLLM response; raw CPA/provider provenance is not required by the user-facing contract. A gateway validation error remains valid error evidence; an unexpected success leaves this criterion unmet; no automatic alternate probe. A2. |
| X-A | A | 4 | Actual OpenCode SSE interruption: after first actual client-visible text, cut the corresponding candidate→CPA response using the coordinated observer. Preserve/record native client resubmissions, distinguish them from gateway dispatches within the original response stream, and record whether the client completes or exits incomplete after its native retry behavior. An incomplete client outcome is a retained limitation, not a blocker, if no same-stream gateway replay occurs. Bound invocation to 180 seconds. No shared-service stop. A2/A3/A5. |
| L-A | A | 1 | One direct real inference while only this candidate's Langfuse delivery is unavailable. Read retained usage and restore delivery without another generation. A5/A6. |
| C-revoked | disposable A-owned key | 1 | After readiness, create then revoke a disposable native key; one request must deny with zero CPA dispatch. Preserve A/A2/B. A4. |
| C-model | A | 1 | One request for a fixed disallowed synthetic alias; denial and zero CPA dispatch. A4. |
| C-rate | disposable A-owned key, native RPM=1 | 2 | Configure one native control key, allow first short request, then repeat once inside the recorded window; observe denial/propagation. This exercises native configured enforcement, not the original 10-RPM threshold or concurrency/overshoot certification. A4. |

Any unexpected forbidden CPA dispatch stops control testing and is a failure.
Native retry limits reached by our cap remain censored observations. Record every
admitted client submission using native request facts, even when one user action
produces several. Record gateway attempts separately. CPA internal/provider
attempts remain unknown unless directly observable; HTTP POST counts or gateway
`num_retries=0` cannot prove the provider's policy.

At checkpoint CPA's mounted config has no explicit retry/fallback policy;
`observability.logs.request-log=false` and `logging-to-file=false`. Before the
live run, resolve the pinned CPA defaults and observation method. Shared CPA
traffic makes an unscoped global counter delta insufficient for forbidden-dispatch
proof. Never pop the CPA usage queue. Protocol stubs/fault-injection checks remain
separate from actual CPA/provider evidence.

## A3: reconcile and persist the shared sample

1. Save response/SSE completion usage and timing plus native request identities
   privately; reconcile S-A/S-A2/S-B and each other admitted request with native
   owner/key, outcome, model, numeric usage and estimated cost. Compare details
   first, then own-key and own-user aggregates; A+A2 belongs to A, B separately.
2. Read at completion, +15, +30, +60 and +120 seconds, stopping once the selected
   records appear. These are bounded observations, not a promised freshness SLA.
   Record first-seen lag as an interval between absent/present reads. A later
   readback investigates persistence, never authorizes another inference.
3. Compare supplied inclusive input/output totals and cache/reasoning subsets
   without adding subsets again. Preserve unknowns, original values and provenance.
   Distinguish native retained cost from API-equivalent expectation and subscription
   expenditure. The 100 input/20 cache/40 output/10 reasoning example in the spec
   is a semantics check, not manufactured provider evidence.
4. Give #6 the retained sample manifest and write-settling observation. Coordinate
   one candidate restart/readback for A3 and a separate offline restore-history
   drill for #6. Read the same completed request after restart; never replay it.
   Keep the original sample and accounting interval if recovery loses a record.

## A5: actual native telemetry and sink outage

Before shared inference, #8 supplies its selected native integration/config,
trusted mapping, server-owned destination/test project, any selected minimal hook,
and a candidate-only payload observation/outage method. Keep the shared Langfuse
service running. An instrumented transport must preserve the actual native
payload; a hand-built telemetry payload is not delivery evidence.

For the same cases, inspect actual outgoing native payload **and** destination
readback. Record prompt/source snippet, output, tool name/arguments/result, image
representation, error detail, original timing, model, supplied tokens and estimated
cost separately as present/missing/truncated. Tool results exist only after they
are sent back; local execution and unsent files cannot be claimed visible.

Use fixed synthetic markers for auth-header/API/OAuth/provider/management-key
fields where the selected transport exposes them, including useful errors and
visible tool/image cases. Compare against #8's declared targeted masking coverage.
Keep useful application content. Scan private payloads for known real fixture and
service credentials without printing matches. Do not claim universal secret
removal from arbitrary code/text. Verify key-owner `userId`, owner/deployment-scoped
session/fallback mapping and forged-metadata handling; caller metadata cannot
redirect delivery. Trace `userId` is analysis, not reader authorization. Link #6's
actual native project membership/role and retention record.

For L-A, make only candidate telemetry unavailable using #8's coordinated seam,
submit once, then observe successful inference/native usage. Retain attempted
native delivery/error facts, restore the transport, and inspect native retry/loss
behavior for a bounded 120-second window. Observe CPA dispatches throughout;
telemetry recovery must cause zero new inference. Record missing trace/delivery
limitations rather than repair them by replaying generation.

## A6: optional dependency and native walkthrough

Record candidate services, mounts, environment and dependency/network topology.
Verify no CPAMP credential/endpoint/read dependency in the candidate configuration,
then combine S-A's healthy inference with populated ordinary-user Usage. CPAMP
may remain running on the shared provider network as the sole existing queue
consumer; its mere presence does not make it a candidate dependency. Do not stop
or drain that shared service to manufacture an independence test.

Once populated, open native history/detail and apply time, model and key filters
once. Compare displayed results with the same native sample and record observed
lag, rounding, absent fields/panels and useful detail availability. Have #1 record
baseline acceptance or select a concrete #10 gap. For this candidate, the owner
may accept the bounded static independence evidence while explicitly deferring a
CPAMP-unavailable runtime inference check; do not claim that deferred scenario
was tested. Navigation/empty counters alone do not complete A6. Keep adopted
architecture and production cutover separate.

## Closing a tranche

Update sanitized [results](acceptance.md), evidence JSON and `DEVELOPMENT.md`.
Validate Markdown links, JSON, private modes and changed-file credential absence;
run focused tests only for substantive custom code changes. Preserve observed
failures and inconclusive checks. Merge the current integration tip before
reporting commits and A1–A6 pass/fail/blocked status. No push, issue closure or
acceptance/adoption decision is implied by this checkpoint.
