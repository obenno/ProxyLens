# Issue tracker

ProxyLens implementation specs live in GitHub Issues; use `gh`. Target implementation
branches and PRs at `dev`, keeping issue scope independently testable. Shared
candidate contracts live in `docs/specs/litellm-poc.md`; issues own work-specific
acceptance and progress.

## October 29 architecture revision

The owner chose in-place revision and native-first personal Usage, then requested
consolidation of work already supplied by LiteLLM.
Read `docs/planning/architecture-rebaseline-2026-10-29.md` for publication status,
the old/new issue map and immutable archives. Published active work is #1/#2/#6/#7/#8;
#4/#5/#9 are closed as consolidated into #7/#2/#2, #3 is open/optional and #10
open/deferred. Original implementation evidence belongs to the old scopes.
Distinguish superseded work from completed runtime criteria; the consolidated
issues were closed as `not_planned`, not completed implementation.

## Required issue structure

Each implementation issue should include:

- **Problem / outcome** — who needs the capability and why.
- **Scope** — what the issue owns.
- **Dependencies** — prerequisite issues, external services, or validation gates.
- **Acceptance criteria** — testable Given/When/Then or checklist criteria.
- **Non-goals** — adjacent work intentionally excluded.
- **Operational notes** — secrets, persistence, health, backup, or rollback behavior where relevant.

## Architecture constraints

- Candidate: LiteLLM owns native accounts, user-owned keys, admission/limits and
  retained client-request accounting; CLIProxyAPI owns provider OAuth/runtime.
  Native personal Usage and native asynchronous Langfuse are the starting points.
- Keep key-owner attribution distinct from interactive actor, customer metadata
  and provider account. Personal scope is enforced server-side before aggregation.
- CPAMP is optional provider-side diagnostics and the sole CPA queue consumer when
  enabled. Personal totals do not require CPAMP joins; dependent enrichment does.
- Configure native features and document their selected semantics; avoid separate
  implementation tickets or upstream feature-test suites. #7 owns shared A1–A6
  integration checks. Custom code needs a demonstrated selected gap and focused
  regression tests. Stronger guarantees require explicit scope and evidence.
- Native-first delivery and deferred advanced reporting are explicit scopes. Keep optional
  plugins, SSO and diagnostics from becoming accidental baseline dependencies.
- Keep management/provider credentials server-side; metadata-only observability,
  unknown-data semantics and no provider replay apply to the candidate.
- Existing runtime: ADR 0001 continues to govern Keycloak/group identity, custom
  authorization and CPAMP-derived proof-gated projections until accepted cutover.
  Proposed ADR 0002 does not silently supersede it.

## Labels and sequencing

Use labels such as `architecture`, `p0`, `p1`, `poc`, `security`, `integration`, and `operations` when available. State blocking dependencies explicitly in the issue body. Link follow-up issues rather than expanding a completed issue beyond its acceptance criteria.
