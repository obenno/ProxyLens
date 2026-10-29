# Architecture and issue rebaseline: October 29, 2026

## Status and owner choices

**Published to GitHub on October 29, 2026, with owner approval.** The owner
selected in-place revision and native-first personal Usage, then requested task
consolidation because much of the first draft duplicated native LiteLLM features.

The [shared plan](../specs/litellm-poc.md) now specifies five active tickets
including the coordinator, three consolidated tickets and two optional/deferred
tickets. Native capabilities are configuration work, with one shared integration
acceptance pass. Custom development requires a demonstrated selected gap.
[ADR 0002](../adr/0002-litellm-personal-usage.md) remains proposed; ADR 0001 governs
the existing runtime. Deferred handoff scenarios are not recorded as passed.

## Published issue map

| Issue | Disposition | Revised responsibility | Dependency |
|---|---|---|---|
| #1 | Active coordinator | Native-first scope, integration results and candidate decision | #2/#7/#8 evidence; #6 readiness before cutover. |
| #2 | Active configuration | Pinned stack, native accounts/keys/limits/Usage and CPA route | #1 setup choices; absorbs #5/#9. |
| #3 | Optional | CPA/CPAMP operator diagnostics and joins, only if needed | #2/#7; never a personal-usage blocker. |
| #4 | Closed; consolidated into #7 | CPA usage sample reconciliation in integration acceptance | Preserve original CPAMP adapter history; no new accounting project. |
| #5 | Closed; consolidated into #2 | Native account/role setup | No custom identity implementation. |
| #6 | Active production readiness | Deployment restore/rollback, retention and controlled cutover | Prepare after #2; cutover after #1 acceptance and approval. |
| #7 | Active integration acceptance | Actual client, personal attribution/access, native usage, controls and telemetry | #2/#8; absorbs #4 and shared feature checks. |
| #8 | Active configuration/integration | Native Langfuse, trusted mapping and redaction | #2; joint verification in #7. |
| #9 | Closed; consolidated into #2 | Native personal keys and configured limits | No custom key/policy engine. |
| #10 | Deferred gap work | Extra reporting only after native UI use identifies a selected gap | #7 findings and explicit feature selection. |

Issues #4/#5/#9 were closed as **superseded/consolidated**, using GitHub reason
`not_planned` and comments naming #7/#2/#2 respectively. This is not completed
replacement implementation. All other issues remain open: five active, #3 optional
and #10 deferred. Existing labels, implementation evidence and unresolved old gates
are retained. All candidate runtime acceptance checkboxes remain unchecked.

## Work removed from the initial milestone

- Separate native login, key lifecycle, budget and dashboard implementation suites.
- A preplanned canonical reporting schema, read adapter, normalizer or projection
  store when native Usage suffices.
- Repeated full-role/endpoint matrices across multiple tickets.
- Broad upstream crash-loss, strict-overshoot, replay and throughput certification
  without an explicit product requirement.
- A custom exporter/outbox before a native delivery gap is demonstrated.

The small A1–A6 checks validate our wiring and actual client. Project-written
authorization/capture/hooks receive focused regression tests; stronger durability
or limit guarantees require additional acceptance before they can be claimed.

## Historical record

`archive/issues-before-2026-10-29.json` is the exact pre-edit GitHub snapshot,
including number, title, body, state, labels, URL and `updatedAt`. It is immutable
history; GitHub remains authoritative for live issue progress.

`archive/issues-after-2026-10-29.json` records verified published titles/bodies,
states, closure reasons, labels and timestamps. Both snapshots are historical
records, not separate live backlogs.

Current component docs describe old implementation contracts and link to this
revision. Historical references to #1–#10 refer to archived scopes. Existing
implementation/evidence remain in `DEVELOPMENT.md` and `docs/live-acceptance.md`.
Owner-provided research files remain intact.

## Review and verification

The owner approved publishing the consolidated plan. Compared all ten live issues
against the original snapshot before editing; there were no intervening changes.
Rechecked each issue immediately before mutation. Updated titles/bodies only,
then closed the three consolidated issues with explanatory comments.

Read back all ten issues through the GitHub API: exact title/body matches,
unchanged labels, expected open/closed states and `not_planned` closure reasons
confirmed. Saved the after-snapshot above. Local Markdown links, issue structure,
A1–A6 ownership and P1–P13 disposition coverage were checked; `git diff --check`
passed. Repository documentation and snapshots are local working-tree changes;
this publication did not commit or push them.

No replacement runtime deployment, model request or integration acceptance was
run as part of these specification edits. ADR 0002 remains proposed.
