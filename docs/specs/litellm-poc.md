# LiteLLM personal-usage integration plan

**Date:** 2026-10-29  
**Status:** owner-approved backlog revision; GitHub issues published October 29, 2026. Candidate runtime acceptance remains pending.  
**Objective update:** native Langfuse debugging traces approved and issue revisions published October 29, 2026; configuration and shared acceptance remain pending.

**Tracker:** [revision map](../planning/architecture-rebaseline-2026-10-29.md).
GitHub Issues own executable work; this document owns the shared scope.

## Outcome and responsibility

Deploy **LiteLLM → CLIProxyAPI (CPA)** for authorized subscription-backed access,
native personal accounts/keys/Usage, and native asynchronous Langfuse debugging
traces with request/response content. Use upstream features as delivered.
ProxyLens owns deployment, configuration and integration;
custom code addresses only a demonstrated gap in an agreed requirement.

The owner selected in-place ticket revision and native-first personal Usage, then
requested consolidation because the first draft duplicated native LiteLLM work.
This revision removes separate account, key, accounting and dashboard implementation
projects, and replaces broad upstream revalidation with bounded integration checks.

The owner's later October 29 choice, “yes, please modify our recorded objective,
use native langfuse integration”, selects the [debugging trace objective](#native-debugging-traces).
It supersedes the candidate's metadata-only/no-content requirement and the proposed
blanket filtering adapter. The [decision record](../candidate/decisions.md#owner-approved-tracing-objective-october-29-2026)
distinguishes this target from the currently disabled integration.

[ADR 0001](../adr/0001-architecture-boundaries.md) still governs the current
implementation; [ADR 0002](../adr/0002-litellm-personal-usage.md) is proposed. The
original [handoff](../research/architecture-handoff-2026-10-29.md) supplies research
and deeper test scenarios, not an instruction to implement every scenario as an
initial release gate. Deferred scenarios are not passed evidence. Adoption and
cutover remain explicit decisions.

## Candidate topology

```text
Clients / IDE / SDK --> LiteLLM --> CPA --> Authorized subscriptions
                          |
                          +--> Native accounts / keys / limits / personal Usage
                          +--> Native persistent database
                          +--> One native async integration --> Langfuse

CPA usage queue --> CPAMP (optional operator diagnostics; sole queue consumer)
```

| Capability | Delivery approach | Project work |
|---|---|---|
| Native login, accounts and roles | Use LiteLLM | Configure ordinary-user access in #2. |
| Personal keys, restrictions, budgets/rates | Use LiteLLM | Configure native policy in #2; representative checks in #7. |
| Spend/history and personal Usage | Use LiteLLM database and UI | Enable/configure in #2; reconcile a small CPA sample in #7. |
| Provider OAuth and execution | Keep CPA | Configure route in #2; actual-client checks in #7. |
| Langfuse debugging traces | Use one native asynchronous integration | Configure content capture and trusted mapping in #8; a minimal hook requires a demonstrated, selected mapping/credential gap. |
| Extra personal charts or missing retained fields | Deferred, gap-driven | #10 starts only after the native UI is used and a gap selected. |
| Provider-account diagnostics | Optional | #3; no dependency for personal totals. |
| Recovery and migration | Deployment-specific | #6 before production cutover. |

Native features need no ProxyLens implementation or duplicate unit-test suite.
Confirm the selected version/edition and configuration, then exercise the deployed
path once. Add focused regression tests for our custom hooks/adapters or a concrete
integration defect; expand tests when a failure or explicit stronger guarantee
justifies them. Do not reproduce upstream password recovery, CRUD, UI-filter or
budget-algorithm test matrices merely because the features are used.

## Work packages

Five active tickets, including the coordinator:

1. **#1 Scope and adoption:** required actual client, native-first feature scope,
   decisions only where configuration needs them, and evidence/limitations summary.
2. **#2 Configure the stack:** pinned Compose, database, CPA route/secret, native
   account roles, user-owned keys, model/limit settings, native logs and Usage.
3. **#8 Configure Langfuse:** one native integration for content-bearing debugging
   traces, trusted owner/session mapping and targeted credential masking.
   Configuration first; no replacement exporter, outbox or preplanned content-stripping hook.
4. **#7 Integration acceptance:** one shared small fixture exercises the assembled
   client → gateway → CPA → native Usage/Langfuse path. Avoid repeated tests in
   each feature ticket.
5. **#6 Production readiness and cutover:** actual backup/restore, state ownership,
   native Langfuse project access and content retention, upgrade/rollback and
   migration for this deployment.

Original #5 and #9 are consolidated into #2; #4 into #7. They were closed with
GitHub reason `not_planned` and explicit consolidation comments on October 29,
2026. Their archived contracts and old implementation evidence remain available;
closure does not mean successful replacement acceptance. #3 stays open/optional.
#10 stays open/deferred pending a demonstrated reporting gap.

```text
#1 scope --> #2 deployment/native configuration --> #8 Langfuse configuration
                     |                                  |
                     +--------------> #7 <--------------+
                                      |
                              #1 candidate decision
                                      |
                             #6 approved cutover

#6 readiness preparation can start after #2.
#3 optional diagnostics; #10 deferred reporting gaps.
```

## First usable milestone

Use native login, personal keys, totals/history/details and native filters. Display
the usage and timing the selected CPA path supplies; record unsupported measurements
instead of fabricating zeroes or implementing a full statistics pipeline.
Configure native limits using documented behavior. No strict never-overspend,
lossless accounting or exactly-once telemetry guarantee is part of this baseline.

Dedicated reasoning/cache trends, latency percentiles, heatmaps, measured RPM/TPM,
broad exports, a separate reporting UI, plugin embedding and provider-account UI
are follow-up scope. A missing field/panel only becomes a custom build task after
the owner selects it as necessary. Wrong ownership, credential exposure,
unauthorized access or broken required client protocol is an integration blocker,
not optional polish.

## Retry boundaries

The owner's [October 29 clarification](../candidate/decisions.md#owner-approved-retry-boundaries-october-29-2026)
preserves native client retry behavior. **The gateway must not silently restart an
interrupted generation within the same response stream.** Apply that boundary
through LiteLLM and CPA; distinguish a new client submission from gateway/provider
attempts serving an already admitted request.

| Layer | Configuration and evidence to record in A2 |
|---|---|
| Client / SDK / OpenCode | Preserve native retries, including new submissions after visible output. Record version, transport, timeouts, retry/fallback settings and observed submissions. Client retries alone are not a compatibility blocker. |
| LiteLLM / router | Record effective retry/fallback settings and observed dispatches, distinguishing pre-output attempts from interruptions after output starts. No silent generation restart within the same response stream. Current configured zero retries does not prevent client retries or establish CPA policy. |
| CPA / provider execution | Record the selected CPA retry/fallback policy separately and correlate visible attempts where available. Preserve the same-stream boundary; hidden provider attempts remain unknown rather than inferred from LiteLLM settings or client POST counts. |

Account for **observed admitted client requests** using native retained request
identities, owner attribution, outcomes and supplied usage. A client retry that is
admitted as a new request belongs to that request's native facts; gateway/provider
attempts remain separate views, not additive consumption. Keep missing records,
usage and unobserved attempts explicit. No strict end-to-end one-user-action /
one-request, lossless accounting or custom user-action deduplication is promised.

Never replay inference to repair usage or telemetry. Sink failure, missing usage
or usage/telemetry recovery must not trigger a new generation; retrying delivery of
an existing telemetry payload follows documented native delivery semantics.
No custom anti-retry/dedup mechanism or OpenCode modification is selected. #7
records the deployed behavior; the [local preflight summary](../candidate/decisions.md#local-client-preflight-reclassification)
is client-only evidence, not an A2 pass.

## Native debugging traces

Langfuse should support application debugging through **one native LiteLLM
Langfuse integration/configuration**. #8 configures it; #7 verifies the deployed
path with A5. The selected objective is:

- Expose prompts, including source code transmitted in requests, AI outputs,
  tool names/arguments/results visible to the integration, useful error details,
  model, original request timing, tokens and estimated cost. Native fields may be missing or
  truncated; record those limits and unknown/unsupported measurements explicitly.
  Reuse A2's success, streaming, tool-continuation and error/interruption samples
  to record actual native coverage and gaps.
- Observe only what reaches the integration. A local tool result can be observed
  only if sent back in a request; the gateway does not observe local tool execution
  or files never transmitted. This objective does not promise a complete local-agent trace.
- Apply targeted credential masking to authorization headers, API/OAuth/provider/
  management credentials, including any surfaced in diagnostic fields. Keep useful debugging
  content. This is not a guarantee of automatic removal of every secret embedded
  in arbitrary prompts, source code or tool content.
- Verify stable key-owner `userId` and owner/deployment-scoped `sessionId` mapping
  from trusted state. Caller `user`/trace/session metadata cannot impersonate
  another owner or override trusted attribution. Unverified conversation IDs need
  an owner-scoped, labeled fallback. The destination/project stays server-controlled;
  caller metadata cannot redirect it. `userId` is an analysis dimension,
  not access authorization. #8 records the trusted destination/project and mapping;
  #6 records native project membership/roles, who may read traces, and content
  retention/deletion using capabilities available in the selected edition.
  No additional bespoke UI/access project is selected.
- Start with native configuration. Only a narrowly selected, demonstrated
  attribution/session-mapping or credential-masking gap can justify a minimal
  hook with focused regression tests. No mandatory adapter, replacement exporter,
  outbox or blanket content-stripping hook is selected. Record native asynchronous
  delivery limitations; usage/telemetry failures must not trigger inference replay
  under the [retry boundaries](#retry-boundaries).

The checked-in disabled capture/callback settings are setup evidence, not the
target behavior; see [deployment status](../candidate/deployment.md#current-logging-settings-and-8-target).
Content capture in Langfuse does not itself require duplicating prompts in native
spend logs or enabling verbose process logs. #8 records the exact effective native
settings and their scope when implementing this objective.

## Bounded integration acceptance (#7)

Use users A/B with personal keys and a second key for A, an administrator for setup,
one service-owned CPA credential and a separate Langfuse test project. Use the
ordinary role actually selected; check additional roles only if enabled. Share
synthetic cases across the checks below and reuse their request/usage evidence.

| Check | Minimum evidence |
|---|---|
| A1 Native access configuration | A/B log in and see their own keys/usage. One representative direct request for B's detail/history as A is denied; do not grant admin access to make personal views work. |
| A2 Actual-client compatibility | Nonstreaming and streaming Responses, tool call/result continuation, plus image/history/ancillary routes actually used by the selected client. Check one upstream error and interrupted stream: the gateway must not silently restart an interrupted generation within the same response stream. Preserve native client retries; record client/LiteLLM/CPA retry/fallback settings and observed submissions/dispatches, and reconcile observed admitted requests with native retained facts under [Retry boundaries](#retry-boundaries). |
| A3 Ownership and usage | A's two keys aggregate to A; B stays separate. Compare the sample's returned numeric usage with native retained details/totals, including supplied cache/reasoning fields. Missing usage/prices remain explicit; do not double-count subsets. Confirm a completed request remains after restart. |
| A4 Configured controls | One revoked-key denial and one model restriction denial, with no forbidden CPA dispatch; exercise one configured budget/rate limit. Record native enforcement/propagation semantics rather than promise immediate or strict behavior. Test more policies only if actually enabled. |
| A5 Langfuse integration | Inspect actual native payload/readback for the shared sample: prompts including transmitted source code, AI outputs, visible tool names/arguments/results, useful errors, model/timing/tokens/estimated cost, with explicit native coverage, missing/truncated fields and image handling. Verify trusted owner/session IDs; forged metadata cannot override them or redirect the configured destination. Use selected tool/image/error cases and synthetic auth-header/API/OAuth/provider/management-key markers to verify the declared targeted masking coverage. Record native project access; `userId` filtering is not authorization. With the sink unavailable, inference remains usable; usage/telemetry failure must not trigger inference replay. Native client retries remain permitted under [Retry boundaries](#retry-boundaries). |
| A6 Optional dependencies and usability | Native Usage and healthy inference work without CPAMP. Walk through native history/filters once, record observed reporting lag and missing panels, and obtain acceptance of the baseline or a specific gap decision. |

Record versions/digests/config, schema, client and route once for the shared run;
record case results, observed lag and limitations. Use synthetic debugging content
and credential markers; keep real credentials and private prompt/code/output/tool
content out of committed evidence. Evidence may be a reproducible runbook and
sanitized results; new automated harness code is needed only where it earns ongoing
regression value.

### What happened to P1–P13?

Preserve traceability to the handoff without treating its entire research matrix
as a native-feature certification project:

| Handoff scenario | Current disposition |
|---|---|
| P1 protocol | A2, restricted to the actual client and selected route. |
| P2 isolation | A1 plus A5 trusted mapping; exhaustive testing is required for any future custom authorization surface, not every unmodified upstream endpoint. |
| P3 lifecycle | Native configuration and A3/A4 sample; full lifecycle/cache permutation testing deferred. |
| P4 metering | A3 sample reconciliation; custom normalization/capture tests only if implemented. |
| P5 budgets | A4 configured-control check; concurrency/overshoot certification only if a strict-budget requirement is later adopted. |
| P6 dashboard | A6 native walkthrough and gap list. |
| P7 rebuild | No custom projection/read adapter in baseline. Activate for #10 if one becomes necessary. Native backup/restore remains in #6. |
| P8 crash accounting | One persisted-record restart check in A3 and deployment recovery in #6; detailed crash-loss injection deferred unless a stronger durability requirement is selected. |
| P9 attribution/redaction | A5 under the owner-approved content-bearing debugging objective: verify trusted mapping, useful visible content and targeted credential masking. The handoff's no-content expectation is superseded; focused hook tests apply only to a demonstrated, selected mapping/credential gap. |
| P10 delivery | A5 sink outage; native delivery semantics documented. Durable outbox/ambiguous-ack experiments deferred unless required. |
| P11 login/edition | Configuration check in #2 and A1; external sessions/plugins deferred with #10. |
| P12 CPAMP independence | A6; diagnostic joins tested only when #3 is selected. |
| P13 operations/performance | Deployment-specific restore/rollback in #6. Record observed latency; capacity benchmarking needs a concrete workload/SLO and separate scope. |

This narrows the first draft's acceptance scope. It does not establish that the
deferred durability, performance, replay or strict-limit scenarios pass.

## Integration contracts to preserve

- Platform ownership comes from authenticated server-side key state. An admin
  creating a key must assign its intended user explicitly. Key owner, interactive
  actor, caller-supplied customer label and provider account are separate concepts.
- Keep historical owner identity stable across personal key changes. Do not infer
  old group-owned machine history from key creator or current group membership.
- CPA inference, CPA management and end-user credentials have distinct purposes.
  Keep privileged keys server-side; only CPAMP consumes a selected CPA usage queue.
- Client-request totals and provider-attempt/CPAMP totals are different views of
  execution, not additive consumption. Langfuse is not authorization or accounting.
- Use native retained records; no custom ledger, canonical event schema, replay
  worker or new database is required for the native-only milestone.
- When interpreting usage, preserve unknowns and provenance. For verified inclusive
  inputs 100/20 cache-read/0 cache-write and output 40/10 reasoning, exclusive
  buckets are 80/20/0/30/10, total 140. This is a check, not a required new normalizer.
- Keep estimated API-equivalent cost, internal allowance and subscription expenditure
  distinct. Select explicit prices for CPA aliases if native pricing cannot resolve
  them; unknown prices cannot be treated as credible zero spend.
- Use the [native debugging trace contract](#native-debugging-traces) for candidate
  content, trusted attribution and targeted credential masking. Native project
  access governs trace readers; analysis filters do not establish personal isolation.

## Decisions at the point of use

| When | Decision owner | Decision |
|---|---|---|
| Setup | #1/#2 | Actual client/model, selected image/edition, deployment endpoints and CPA isolation; native role, enabled model/limit settings and prices. Record upstream defaults deliberately where acceptable. |
| Telemetry setup | #8 | One compatible native integration/destination, content capture, targeted credential masking, trusted owner/session mapping and documented native delivery semantics; record actual settings and any demonstrated selected gap. |
| Candidate acceptance | #1/#7 | Accept native UI/metrics and observed integration behavior, or identify a concrete blocker/gap. No empty quantitative threshold is called passed. |
| Production use | #6 | Native Langfuse project access/roles and content retention/deletion, backup/restore, key issuance, old-history handling and rollback. Any stricter budget, loss, freshness or capacity requirement needs its own measured acceptance. |
| Custom extension | #10 | Required panel/field, supported read interface, ordinary-user session and retained-data/replay boundary. Decide only if the extension is selected. |

The earlier 60-second freshness and 90/365/90-day retention figures remain proposed
starting values, not native guarantees. Recording current behavior does not promise
strict budgets or crash safety. Explicitly document accepted native limitations.

## Adoption and cutover

#1 reviews A1–A6, native configuration, unresolved gaps and documented limitations.
On acceptance, update ADR 0002, ADR 0001 status, glossary and guidance together.
#6 completes deployment-specific readiness before separately approved production
cutover: backups, replacement keys, ingress switch, history semantics and rollback.
Retire old components after replacement/cutover acceptance. Do not replay production
requests merely to compare accounting. Historical tests remain old-path evidence.

## Capability references

Official docs checked October 29, 2026 confirm the native reuse direction:
`https://docs.litellm.ai/docs/proxy/self_serve`,
`https://docs.litellm.ai/docs/proxy/virtual_keys`,
`https://docs.litellm.ai/docs/proxy/users`, and
`https://docs.litellm.ai/docs/observability/langfuse_integration`.
These live pages do not pin the deployed release. #2 records the selected version
and available edition; no upgrade or replacement deployment occurred in this revision.
