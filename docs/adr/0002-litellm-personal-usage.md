# LiteLLM-owned personal access and accounting

---
status: proposed
date: 2026-10-29
---

The clarified product needs personal keys and usage rather than mandatory group
administration. Propose LiteLLM for native accounts, user-owned virtual keys,
admission, limits and client-request accounting, with CLIProxyAPI retained for
provider OAuth and execution. Prefer native personal Usage and native asynchronous
Langfuse integration for content-bearing application debugging; limit ProxyLens
custom code to demonstrated reporting and integration gaps. This avoids
reconstructing every personal owner from a CPAMP join while retaining the provider
runtime already exercised by the project.

## Status and adoption

This is the candidate for the [POC contract](../specs/litellm-poc.md), not an
accepted replacement. [ADR 0001](0001-architecture-boundaries.md) remains accepted
for the checked-in implementation. Bounded integration acceptance, documented native
semantics and owner acceptance are required before changing either status. Revising issue
titles or passing old-stack tests does not establish acceptance.

## Consequences

- The platform user owns personal virtual keys. Historical ownership is captured
  at admission; `key_owner` attribution is distinct from a verified interactive
  actor and from caller-supplied customer metadata.
- Configure native features instead of creating parallel account/key/reporting
  projects or duplicating upstream tests. One shared integration pass validates
  this deployment; custom hooks/adapters receive focused regression tests.
- LiteLLM retained facts are the proposed personal accounting source. Document
  native durability and limit semantics; strict budgets, lossless accounting or
  custom rebuildability require separately selected scope and evidence.
  Subscription expenditure remains a separate concept.
- CPAMP is optional operator history/diagnostics and remains the only CPA queue
  consumer when enabled. CPA/CPAMP joins gate only dependent enrichment, not basic
  personal ownership or totals. Never add both systems' totals as independent use.
- Native login and personal Usage are the initial UI. A separate reporting UI
  requires a supported authenticated session and server-side scoping. Plugin
  claims and admin-only routes do not supply ordinary-user authorization.
- The owner's [October 29 tracing decision](../candidate/decisions.md#owner-approved-tracing-objective-october-29-2026)
  selects one native asynchronous LiteLLM Langfuse integration for prompts
  (including transmitted source code), AI outputs, visible tool names/arguments/
  results, useful errors and model/timing/tokens/estimated cost. It supersedes the
  candidate metadata-only requirement; [A5](../specs/litellm-poc.md#bounded-integration-acceptance-7)
  verifies content, trusted owner/session mapping and targeted credential masking.
  Native project access/roles and content retention belong to #6; `userId` is an
  analysis dimension, not authorization. Unsent files/local tool execution are
  outside gateway visibility; automatic removal of all embedded secrets is not
  promised. Record native missing/truncated fields for owner review; use native
  project controls without a bespoke UI/access project.
- Configure the native integration first. Only a demonstrated, narrowly selected
  mapping/credential gap justifies a minimal hook with focused regression tests.
  No mandatory adapter, replacement exporter/outbox or preplanned content-stripping
  hook is selected. Record native delivery limitations; stronger guarantees need
  separately selected scope and evidence.
- Keycloak, group-owned resources, the custom public gateway, CPAMP projections
  and custom exporter remain valid under their existing contracts until approved
  cutover. Preserve historical evidence; issue new keys where migration cannot
  preserve guarantees, and keep old history's original ownership semantics.

## Alternatives and rationale

Retaining the custom stack preserves implemented group controls but keeps a larger
custom identity, forwarding and projection surface than the personal product
requires. The [handoff](../research/architecture-handoff-2026-10-29.md) records
Sub2API and New API alternatives; LiteLLM is the first experiment because of its
researched personal usage, extension and Langfuse fit. This is not a measured
reliability ranking. Revisit the candidate if required client behavior, OSS access,
accounting or reporting cannot meet the contract without broad gateway changes.
