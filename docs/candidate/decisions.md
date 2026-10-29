# Candidate setup decisions and evidence status

**Recorded:** October 29, 2026. **Status:** issue #1 setup-scope tranche only;
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
| Langfuse resource | Existing authorized Langfuse test service where available, with a separate test project and one native asynchronous integration; metadata-only capture. | #8 verifies destination/project isolation, compatible integration, trusted owner/session mapping, redaction and native delivery settings; #7 supplies A5 evidence. |
| Reporting | Use native totals/history/details/filters first; preserve missing measurements and unknown prices explicitly. | #2 records resolved pricing or explicit API-equivalent price overrides and provenance; #7 reviews retained usage, reporting lag and UI limitations. |

Reason: configure upstream personal access and reporting first, then assess concrete
integration gaps. A selected community edition, role or callback is not proof that
the required behavior works. If a required capability is unavailable, record a
blocker for the owner rather than silently changing edition, access scope or client.
Estimated API-equivalent cost, allowance consumption and subscription expenditure
remain separate; unknown prices are not credible zero spend.

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
| #2 stack/native configuration | Implementation delegated; no configured-candidate evidence recorded here. | Verified pins/edition/model, reproducible configuration and native account/key/Usage setup. |
| #8 native Langfuse | Required; no configured-integration evidence recorded here. | Configure after #2; share A5 evidence through #7. |
| #7 acceptance | **A1–A6 unperformed.** | Assembled #2/#8 candidate and one shared fixture. |
| #6 production readiness | Later deployment-specific work; production cutover not authorized. | Restore/rollback, retention, key issuance/history plan, candidate acceptance and separate cutover approval. |
| #3 diagnostics | **Optional, unselected.** | Select only for a concrete operator diagnostic need; never gates personal totals. |
| #10 reporting extension | **Deferred, unselected.** | Use native UI in A6, identify a gap and obtain explicit feature selection. |

#4 is consolidated into #7; #5/#9 into #2. Their closure is consolidation, not
candidate acceptance. CPAMP remains the sole CPA usage-queue consumer when enabled;
the candidate must work without it. No new queue consumer or CPAMP-dependent
personal ownership is selected.

## Evidence register

**Observed in this tranche:** read local contracts and live
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
| A5 Langfuse | **Unperformed** | Trusted owner/session, content/credential redaction, forged-metadata rejection and sink outage without replaying provider work. |
| A6 Independence/usability | **Unperformed** | Inference and native Usage without CPAMP; history/filter walkthrough, observed lag/gaps and owner baseline/gap decision. |

#2 records exact versions/digests, edition/schema, model/route, role, policies,
pricing, sanitized configuration and reproduction steps once; #8 adds destination
and telemetry settings. #7 links those settings to dated, sanitized case results,
retained records, observed lag and limitations. Never commit credentials or content.
The exploration handoff at
`/data/tmp/opencode/proxylens-litellm-20261029/exploration.md` is a working input for
the implementers, not acceptance evidence; verified conclusions must be recorded
in repository evidence with their source and limits.

## Remaining #1 decisions

- The first setup acceptance criterion remains partial until #2 records exact
  model/configuration choices. All runtime criteria await #2/#8/#7 evidence.
- Review A1–A6 and native UI limitations before accepting or rejecting the candidate.
  Wrong ownership, privacy leakage or broken required OpenCode behavior blocks
  acceptance. Additional custom work requires a demonstrated, selected gap.
- Preserve the P1–P13 dispositions in the shared spec: deferred/conditional scenarios
  are not passed. No strict-budget, lossless-accounting, exactly-once telemetry,
  freshness or capacity guarantee follows from a smoke check. Earlier proposed
  freshness/retention values remain proposals; #6 owns production choices.
- Architecture adoption requires an explicit owner decision and coordinated ADR
  status, glossary and guidance updates. Production cutover requires separate #6
  readiness and approval. Preserve old history's group ownership and proof limits.
