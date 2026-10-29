# LiteLLM personal-usage integration plan

**Date:** 2026-10-29  
**Status:** owner-approved backlog revision; GitHub issues published October 29, 2026. Candidate runtime acceptance remains pending.  
**Tracker:** [revision map](../planning/architecture-rebaseline-2026-10-29.md).
GitHub Issues own executable work; this document owns the shared scope.

## Outcome and responsibility

Deploy **LiteLLM → CLIProxyAPI (CPA)** for authorized subscription-backed access,
native personal accounts/keys/Usage, and native asynchronous Langfuse. Use upstream
features as delivered. ProxyLens owns deployment, configuration and integration;
custom code addresses only a demonstrated gap in an agreed requirement.

The owner selected in-place ticket revision and native-first personal Usage, then
requested consolidation because the first draft duplicated native LiteLLM work.
This revision removes separate account, key, accounting and dashboard implementation
projects, and replaces broad upstream revalidation with bounded integration checks.

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
| Langfuse transport | Use a native integration | Configure in #8; add a narrow trusted mapping hook only if needed. |
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
3. **#8 Configure Langfuse:** native callback, trusted owner/session mapping and
   metadata-only redaction. Configuration first; no preplanned replacement exporter.
4. **#7 Integration acceptance:** one shared small fixture exercises the assembled
   client → gateway → CPA → native Usage/Langfuse path. Avoid repeated tests in
   each feature ticket.
5. **#6 Production readiness and cutover:** actual backup/restore, state ownership,
   retention, upgrade/rollback and migration for this deployment.

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
the owner selects it as necessary. A wrong owner, privacy failure or broken required
client protocol is an integration blocker, not optional polish.

## Bounded integration acceptance (#7)

Use users A/B with personal keys and a second key for A, an administrator for setup,
one service-owned CPA credential and a separate Langfuse test project. Use the
ordinary role actually selected; check additional roles only if enabled. Share
synthetic cases across the checks below and reuse their request/usage evidence.

| Check | Minimum evidence |
|---|---|
| A1 Native access configuration | A/B log in and see their own keys/usage. One representative direct request for B's detail/history as A is denied; do not grant admin access to make personal views work. |
| A2 Actual-client compatibility | Nonstreaming and streaming Responses, tool call/result continuation, plus image/history/ancillary routes actually used by the selected client. Check one upstream error and interrupted stream; no replay of partial output. |
| A3 Ownership and usage | A's two keys aggregate to A; B stays separate. Compare the sample's returned numeric usage with native retained details/totals, including supplied cache/reasoning fields. Missing usage/prices remain explicit; do not double-count subsets. Confirm a completed request remains after restart. |
| A4 Configured controls | One revoked-key denial and one model restriction denial, with no forbidden CPA dispatch; exercise one configured budget/rate limit. Record native enforcement/propagation semantics rather than promise immediate or strict behavior. Test more policies only if actually enabled. |
| A5 Langfuse integration | The same sample has trusted owner/session IDs and no prompt/output/tool/image/credential content. One forged owner/session metadata case cannot change trusted attribution. With the sink unavailable, inference remains usable and provider work is not replayed. |
| A6 Optional dependencies and usability | Native Usage and healthy inference work without CPAMP. Walk through native history/filters once, record observed reporting lag and missing panels, and obtain acceptance of the baseline or a specific gap decision. |

Record versions/digests/config, schema, client and route once for the shared run;
record case results, observed lag and limitations. Keep credentials and content out
of committed evidence. Evidence may be a reproducible runbook and sanitized results;
new automated harness code is needed only where it earns ongoing regression value.

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
| P9 attribution/redaction | A5; extend focused tests if a custom mapping hook is introduced. |
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
- Prefer one native Langfuse integration with owner/deployment-scoped IDs, original
  timing, numeric usage and bounded metadata. A caller's `user` or trace/session
  fields cannot override trusted attribution. Default content capture stays off.

## Decisions at the point of use

| When | Decision owner | Decision |
|---|---|---|
| Setup | #1/#2 | Actual client/model, selected image/edition, deployment endpoints and CPA isolation; native role, enabled model/limit settings and prices. Record upstream defaults deliberately where acceptable. |
| Telemetry setup | #8 | Compatible native integration/destination, trusted owner/session mapping and acceptance of documented native delivery semantics. |
| Candidate acceptance | #1/#7 | Accept native UI/metrics and observed integration behavior, or identify a concrete blocker/gap. No empty quantitative threshold is called passed. |
| Production use | #6 | Retention, backup/restore, key issuance, old-history handling and rollback. Any stricter budget, loss, freshness or capacity requirement needs its own measured acceptance. |
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
