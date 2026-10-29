# Candidate setup decisions and evidence status

**Recorded:** October 29, 2026; updated for the owner's native tracing objective.
**Status:** issue #1 setup-scope and objective decisions only;
candidate acceptance and architecture adoption remain pending.

The [POC contract](../specs/litellm-poc.md) owns shared scope; live GitHub Issues
own executable work. This record captures the owner's setup selections and the
evidence still required. [ADR 0002](../adr/0002-litellm-personal-usage.md) remains
proposed; [ADR 0001](../adr/0001-architecture-boundaries.md) governs the existing
runtime. See the [rebaseline](../planning/architecture-rebaseline-2026-10-29.md)
for consolidated tickets and preserved historical evidence.

## Selected setup, not observed capability

These choices come from the owner's October 29 implementation instruction.
Availability and behavior on the selected release still require #2/#8 setup and
#7 integration evidence.

| Area | Selected default | Exact settings/evidence owner |
|---|---|---|
| Required actual client | **OpenCode**, using personal keys through LiteLLM → CLIProxyAPI (CPA). | #2 records client version/configuration and authorized model/route; #7 exercises the actual client, including its Responses, tool continuation and used image/history/ancillary paths. |
| Deployment and edition | **Isolated local community-edition POC**, with candidate-owned configuration, database and state. | #2 selects verified version/digest pins and records edition, schema, listeners, service endpoints and isolation. Community-edition ordinary-user access must be demonstrated. |
| Identity and UI | Native ordinary personal users, native keys and native personal Usage. Administrator used for setup; fixture users A/B, two keys for A and one for B. | #2 verifies the exact ordinary-role identifier and explicit key owners; #7 checks personal access without elevating users to administrator. |
| Model and controls | Authorized model allowlist and **conservative native rate limits**. | #2 selects the model from authorized local evidence; records alias/resolved route, exact rate values, units, windows and scope, other enabled policies and deliberately retained defaults. #7 observes enforcement/propagation. |
| CPA resource | Reuse an existing authorized CPA test resource where available, keeping the inference credential server-side. | #2 verifies authorization, route and credential boundary and records how the candidate is isolated from other traffic/state. If no suitable resource exists, record the blocker and required isolated CPA setup. |
| Langfuse resource | Existing authorized Langfuse test service where available, with a separate test project and one native asynchronous integration for content-bearing debugging traces. | #8 configures native content capture, targeted credential masking and trusted owner/session mapping; #7 supplies A5 evidence; #6 records native project access and content retention. |
| Reporting | Use native totals/history/details/filters first; preserve missing measurements and unknown prices explicitly. | #2 records resolved pricing or explicit API-equivalent price overrides and provenance; #7 reviews retained usage, reporting lag and UI limitations. |

Reason: configure upstream personal access and reporting first, then assess concrete
integration gaps. A selected community edition, role or callback is not proof that
the required behavior works. If a required capability is unavailable, record a
blocker for the owner rather than silently changing edition, access scope or client.
Estimated API-equivalent cost, allowance consumption and subscription expenditure
remain separate; unknown prices are not credible zero spend.

## Owner-approved tracing objective: October 29, 2026

After clarifying the desired debugging visibility, the owner explicitly chose:
**“yes, please modify our recorded objective, use native langfuse integration”.**
The [shared trace contract](../specs/litellm-poc.md#native-debugging-traces) now
requires prompts including transmitted source code, AI outputs, tool
names/arguments/results visible to the integration, useful errors and
model/timing/tokens/estimated cost. It supersedes the earlier candidate
metadata-only/no-content requirement and proposed blanket filtering adapter.

Reason: application debugging needs the request/response content. Consequence:
configure one native LiteLLM Langfuse integration first, retaining targeted
auth-header/API/provider-key masking and verified owner/session mapping. A minimal
hook needs a demonstrated, narrowly selected mapping/credential gap; no mandatory
adapter, replacement exporter/outbox or preplanned content-stripping hook is selected.
No automatic all-secret-removal guarantee or visibility into unsent local files/tool
execution is implied. `userId` supports analysis, not authorization; #6 records
native project readers/roles and content retention/deletion without a bespoke
UI/access project. Native fields may be missing or truncated; #7 records those
limits and the owner reviews any required debugging gap.

**Current versus target:** the [#2 deployment record](deployment.md#current-logging-settings-and-8-target)
and checked-in configuration still have message capture and detailed error logs
disabled, spend-log prompt storage off, and no Langfuse callback. The owner choice
authorizes the future #8 setup objective; this documentation change enables no
capture and supplies no A5 evidence. #8 must record the effective settings and
native coverage; #7 must verify them. Prior setup/research findings remain dated
inputs, not a requirement to implement the discarded blanket filtering design.

The coordinator published the matching #1/#2/#6/#7/#8 revisions and verified
readback on October 29; [before/after snapshots and publication details](../planning/architecture-rebaseline-2026-10-29.md#native-tracing-objective-clarification-october-29-2026)
preserve that change. States/labels are unchanged and no acceptance checkbox was
completed by the objective revision.

## Dependency and status snapshot

```text
#1 setup selections → #2 deployment/native configuration → #8 Langfuse configuration
                              |                                  |
                              +------------→ #7 A1–A6 ←----------+
                                                 |
                                      #1 evidence/owner decision
                                                 |
                                      #6 separately approved cutover

#6 readiness preparation can start after #2.
#3 optional/unselected; #10 deferred until a reporting gap is explicitly selected.
```

| Work | Status in this record | Next gate |
|---|---|---|
| #1 setup and coordination | Owner defaults recorded; **partial**, not full issue completion. | #2 exact choices, #7 results and limitations, then explicit owner candidate decision. |
| #2 stack/native configuration | Configuration/startup tranche recorded in [deployment](deployment.md); shared acceptance pending. | #7 verifies actual-client, ownership/usage and controls; #8 implements the revised tracing objective. |
| #8 native Langfuse | Required; callback/content capture still disabled in checked-in setup. | Configure the native debugging objective after #2; share A5 evidence through #7. |
| #7 acceptance | **A1–A6 unperformed.** | Assembled #2/#8 candidate and one shared fixture. |
| #6 production readiness | [Partial same-pin recovery evidence](recovery.md) for native account/key/policy state; production cutover not authorized. | Populated request-history restore, external recovery, native project access/content retention, upgrade/rollback, candidate acceptance and separate cutover approval. |
| #3 diagnostics | **Optional, unselected.** | Select only for a concrete operator diagnostic need; never gates personal totals. |
| #10 reporting extension | **Deferred, unselected.** | Use native UI in A6, identify a gap and obtain explicit feature selection. |

#4 is consolidated into #7; #5/#9 into #2. Their closure is consolidation, not
candidate acceptance. CPAMP remains the sole CPA usage-queue consumer when enabled;
the candidate must work without it. No new queue consumer or CPAMP-dependent
personal ownership is selected.

## Evidence register

**Observed in the original setup tranche:** read local contracts and live
`gh issue view 1 --json number,title,body,state,url,updatedAt` for
`obenno/ProxyLens` on October 29, 2026. Issue #1 was open, last updated
`2026-10-29T07:11:34Z`, with all acceptance criteria unchecked. The clean
`impl/litellm-issue1-scope` worktree started at `414ccc9`;
`git merge-base --is-ancestor integration/litellm-native-poc HEAD` passed.
These are setup/document checks, not runtime evidence.

The [shared A1–A6 definitions](../specs/litellm-poc.md#bounded-integration-acceptance-7)
remain authoritative. No candidate requests, native UI walkthrough or telemetry
acceptance were performed by this tranche.

| Check | Status | Required evidence still outstanding (#7) |
|---|---|---|
| A1 Native access | **Unperformed** | A/B ordinary login, own keys/usage and representative denied cross-user direct read. |
| A2 Actual client | **Unperformed** | OpenCode protocol cases on the selected route, upstream error and interrupted stream without partial-output replay. |
| A3 Ownership/usage | **Unperformed** | A's keys aggregate separately from B; numeric usage reconciliation including supplied subsets/unknowns; completed record survives restart. |
| A4 Controls | **Unperformed** | Revoked-key and model denials without forbidden CPA dispatch; configured rate-limit exercise and native propagation semantics. |
| A5 Langfuse | **Unperformed** | Content-bearing debugging trace readback, targeted credential masking, trusted owner/session and forged-metadata check, project access boundary and sink outage without replaying provider work; see shared A5 for the sample. |
| A6 Independence/usability | **Unperformed** | Inference and native Usage without CPAMP; history/filter walkthrough, observed lag/gaps and owner baseline/gap decision. |

#2 records exact versions/digests, edition/schema, model/route, role, policies,
pricing, sanitized configuration and reproduction steps once; #8 adds destination
and telemetry settings. #7 links those settings to dated, sanitized case results,
retained records, observed lag and limitations. Commit only sanitized evidence with
synthetic content/credential markers, never real credentials or private content.
The exploration handoff at
`/data/tmp/opencode/proxylens-litellm-20261029/exploration.md` is a working input for
the implementers, not acceptance evidence; verified conclusions must be recorded
in repository evidence with their source and limits.

## Remaining #1 decisions

- #2's [recorded model/configuration choices](deployment.md) are setup evidence;
  runtime acceptance still awaits #8/#7 evidence. The revised tracing objective
  remains a target, not an observed capability.
- Review A1–A6 and native UI limitations before accepting or rejecting the candidate.
  Wrong ownership, credential exposure, unauthorized access or broken required
  OpenCode behavior blocks acceptance. Additional custom work requires a
  demonstrated, selected gap.
- Preserve the P1–P13 dispositions in the shared spec: deferred/conditional scenarios
  are not passed. No strict-budget, lossless-accounting, exactly-once telemetry,
  freshness or capacity guarantee follows from a smoke check. Earlier proposed
  freshness/retention values remain proposals; #6 owns production choices.
- Architecture adoption requires an explicit owner decision and coordinated ADR
  status, glossary and guidance updates. Production cutover requires separate #6
  readiness and approval. Preserve old history's group ownership and proof limits.
