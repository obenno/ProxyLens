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

## Native tracing objective clarification: October 29, 2026

**Owner-approved objective; published and verified by the coordinator on October 29, 2026.**
After clarifying the desired application-debugging visibility, the owner said:
“yes, please modify our recorded objective, use native langfuse integration”.
The [live candidate contract](../specs/litellm-poc.md#native-debugging-traces) and
[decision record](../candidate/decisions.md#owner-approved-tracing-objective-october-29-2026)
now select one native asynchronous LiteLLM Langfuse integration with prompts
(including source code sent in requests), AI outputs, visible tool names/arguments/
results, useful errors and model/timing/tokens/estimated cost.

This supersedes the candidate metadata-only/no-content requirement, the original
P9 no-content expectation and the proposed blanket filtering adapter. Native
configuration comes first; only a demonstrated, narrowly selected mapping or
credential-masking gap justifies a minimal hook. No replacement exporter/outbox,
preplanned content-stripping hook or bespoke UI/access project is selected.
Targeted auth-header/API/provider-key masking and verified owner/session mapping
remain required. Native fields may be missing/truncated; there is no automatic
all-secret-removal guarantee or visibility into unsent files/local tool execution.
`userId` is an analysis dimension, not authorization; #6 records native Langfuse
project readers/roles and content retention/deletion. #7's revised A5 supplies
shared evidence, including outage isolation without telemetry-triggered inference replay.

The coordinator published issue #1/#2/#6/#7/#8 revisions. The new #8 title is
**Configure native Langfuse: content-rich debugging traces and attribution**.
Readback verified exact proposed titles/bodies, unchanged states/labels and no
completed acceptance checkboxes. The coordinator supplied exact public-issue
[before](archive/issues-before-native-tracing-2026-10-29.json) and
[after](archive/issues-after-native-tracing-2026-10-29.json) snapshots for this
revision. The original snapshots remain immutable. The map below reflects the
published clarification; publication is not runtime acceptance.

**Initial runtime status:** capture/callbacks were disabled in the original #2
setup recorded in [candidate deployment](../candidate/deployment.md#current-logging-settings-and-8-target).
#8 has since activated the selected native callback and documented its setup;
shared A5 evidence is still pending. This does not establish architecture adoption
or cutover. ADR 0002 stays proposed.

**Historical research:** the [architecture handoff](../research/architecture-handoff-2026-10-29.md),
[stack comparison](../research/new-api-stack-comparison.md),
[original stack research](../research/proxy-stack-research.md) and prior telemetry
research/development notes retain their dated content. Their metadata-only defaults
and blanket filtering proposals are not the live candidate objective. Follow the
linked candidate contract for new work. ADR 0001, old-runtime exporter/test
contracts and old evidence retain their original scope; research is not rewritten.

## Retry-boundary clarification: October 29, 2026

**Owner-approved and published by the coordinator on October 29, 2026.** The owner
accepted the proposal with “good, I will accept that”. The
[retry contract](../specs/litellm-poc.md#retry-boundaries) preserves native client
retries while prohibiting silent gateway generation restart within the same
response stream and inference replay to repair usage/telemetry. #7 records the
client/LiteLLM/CPA retry/fallback boundaries and reconciles observed admitted
requests using native retained facts. No strict one-user-action / one-request
promise, custom anti-retry/dedup mechanism or OpenCode change is selected.

The [sanitized preflight summary](../candidate/decisions.md#local-client-preflight-reclassification)
preserves OpenCode 2.2.1's observed 1 normal / 5 disconnect (capped) / 4 timeout
POSTs. Those are accepted client-only observations, not a compatibility blocker
or deployed A2 pass. The owner decision supersedes the former blocker reading in
recovery/private handoff notes; dated development and historical research remain
intact. Current LiteLLM/router retry=0 is unchanged and cannot prevent client retries.

The coordinator updated #1/#7/#8 and verified exact body readback, unchanged
titles/states/labels and all acceptance criteria unchecked. Exact public-issue
[before](archive/issues-before-retry-boundary-2026-10-29.json) and
[after](archive/issues-after-retry-boundary-2026-10-29.json) snapshots preserve
this revision; earlier archives remain immutable. A2 now distinguishes client
submissions from same-stream gateway behavior; A5/#8 prohibit usage/telemetry-triggered
inference replay without forbidding native client retries. Publication is complete;
runtime A1–A6, candidate acceptance, adoption and cutover remain pending.

## Published issue map

| Issue | Disposition | Revised responsibility | Dependency |
|---|---|---|---|
| #1 | Active coordinator | Native-first scope, integration results and candidate decision | #2/#7/#8 evidence; #6 readiness before cutover. |
| #2 | Active configuration | Pinned stack, native accounts/keys/limits/Usage and CPA route | #1 setup choices; absorbs #5/#9. |
| #3 | Optional | CPA/CPAMP operator diagnostics and joins, only if needed | #2/#7; never a personal-usage blocker. |
| #4 | Closed; consolidated into #7 | CPA usage sample reconciliation in integration acceptance | Preserve original CPAMP adapter history; no new accounting project. |
| #5 | Closed; consolidated into #2 | Native account/role setup | No custom identity implementation. |
| #6 | Active production readiness | Deployment restore/rollback, native Langfuse project access/content retention and controlled cutover | Prepare after #2; cutover after #1 acceptance and approval. |
| #7 | Active integration acceptance | Actual client, personal attribution/access, native usage, controls and telemetry | #2/#8; absorbs #4 and shared feature checks. |
| #8 | Active configuration/integration | One native Langfuse integration, content-rich debugging traces, trusted mapping and targeted credential masking | #2; joint verification in #7. |
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
