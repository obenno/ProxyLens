# ProxyLens architecture research handoff

**Date:** October 29, 2026  
**Purpose:** support the owner's subsequent specification and GitHub issue revision.  
**Status:** recommended direction, conditional on runtime validation; not an adopted architecture or implementation plan approval.

## Executive decision

**First recommendation: LiteLLM → CLIProxyAPI, with native personal usage views,
a small reporting extension for missing CPAMP-style statistics, and asynchronous
Langfuse integration.**

```text
Clients / IDEs / SDKs
          |
          v
       LiteLLM ----------------> CLIProxyAPI ------> Authorized subscriptions
          |                          |
          |                          +--> Usage queue --> CPAMP [optional]
          |                                               Operator diagnostics
          +--> User/key ownership, access and budgets
          +--> Persisted client-request usage
          |       +--> Native personal dashboard
          |       +--> Additional personal reporting [where needed]
          +--> Native asynchronous integration --> Langfuse
```

The key simplification is to establish personal ownership at request admission,
using the authenticated LiteLLM key's owner. Personal reporting would no longer
require reconstructing that ownership by joining every request to CPAMP history.
CLIProxyAPI retains the provider runtime already exercised by this project.

This recommendation **supersedes the October 28 Sub2API-first recommendation** in
[the earlier alternatives comparison](new-api-stack-comparison.md). That document
remains useful evidence about New API and Sub2API. The change in preference follows
the additional LiteLLM research: native personal usage, documented extension
points, and an existing Langfuse integration better match the combined requirement.
It is a product-fit judgment, not a measured reliability or performance ranking.

The owner accepted this direction for a research handoff. Adoption still requires
the POC in section 12 and deliberate revision of the accepted architecture.
[ADR 0001](../adr/0001-architecture-boundaries.md), repository instructions, and
existing issue contracts still describe the Keycloak/group/CPAMP-based system.
This document does not silently replace them.

### Recommended component responsibilities

| Component | Proposed responsibility |
|---|---|
| LiteLLM | Native user accounts, user-owned virtual keys, admission policy, budgets/rate limits, and client-facing request usage/spend. |
| CLIProxyAPI, abbreviated CPA | Provider OAuth, credential refresh/runtime, provider-account selection, translation and provider compatibility. |
| Personal reporting extension | Only the additional authenticated queries, retained fields, aggregates and presentation needed beyond native personal Usage. |
| Langfuse | Redacted user/session-attributed observability through LiteLLM's existing integration; not authorization or accounting authority. |
| CPAMP Full Mode, if retained | Durable CPA-side history and provider-account diagnostics; remains the sole CPA usage-queue consumer. |
| ProxyLens | Deployment/configuration, integration contracts, validation and the small reporting extension rather than a second general-purpose gateway. |

LiteLLM's existing user, callback and Langfuse capabilities are supported by the
research sources; this allocation of responsibilities is the proposed design.
[LL-self-serve] [LL-hooks] [LF-integration]

### Navigation for spec and ticket revision

- [Evidence and version snapshots](#2-evidence-versions-and-confidence)
- [Candidate comparison](#3-why-litellm-is-now-the-first-recommendation)
- [Ownership and identity](#4-proposed-ownership-and-identity-contracts)
- [Native dashboard versus custom work](#5-dashboard-native-baseline-and-custom-scope)
- [Accounting and reporting contract](#6-proposed-request-accounting-and-reporting-data-contract)
- [Plugins and edition boundaries](#7-custom-dashboard-integration-and-edition-boundaries)
- [Langfuse contract](#8-langfuse-integration-contract)
- [CPA compatibility](#9-litellm--cpa-compatibility-boundary)
- [Deployment and operations](#10-deployment-and-operational-implications)
- [Existing-work disposition and spec delta](#11-current-work-disposition-and-specification-delta)
- [POC acceptance gates](#12-focused-poc-and-adoption-gates)
- [Issue-by-issue revisions and work packages](#13-existing-issue-map-and-proposed-follow-up-work)
- [Owner decisions](#14-decisions-left-for-the-owner)
- [Source register](#15-reading-map-and-source-register)

## 1. Product requirement and scope

### 1.1 Clarified requirement

The requested product has three central needs:

1. Expose authorized provider subscriptions through an API usable by the actual
   clients, SDKs and IDEs.
2. Manage usage per person, with distinct credentials, understandable limits and
   ownership that survives multiple keys and key rotation.
3. Give each person a **CPAMP-like statistics dashboard for their own usage**.

Langfuse adds request/session observability. It should integrate asynchronously
without becoming the database that determines authorization or personal allowance.

Keycloak-owned user/group administration and synchronization are **not product
requirements** under this clarification. They remain requirements of the current
accepted implementation until the owner revises that design.

### 1.2 What “CPAMP-like” means here

The personal product should make request counts, input/output/cache/reasoning
usage where available, estimated cost, time/model/key trends, failures, latency,
first-token timing and request drill-down understandable to each user. Exact panel
priorities still need confirmation; section 5 separates native features from gaps.

CPAMP's provider-account health, credential rankings, account quota and operational
controls are a different surface. A personal dashboard does not need to expose
provider credentials or administrator operations. LiteLLM observing one CPA
deployment cannot independently know which credential CPA selected internally.
[CPAMP-analytics] [lite-assessment]

### 1.3 Scope of this handoff

This records the recommendation, evidence, uncertainty, proposed contracts,
existing-work disposition, issue revision suggestions and validation gates. No
replacement stack was deployed during this research. No new provider calls,
application changes, migrations, issue mutations or architecture adoption are
represented by this document. `DEVELOPMENT.md` is intentionally untouched in this
research session, as requested.

## 2. Evidence, versions and confidence

### 2.1 Evidence labels

Use these distinctions when turning this research into acceptance criteria:

| Label | Meaning |
|---|---|
| **Source-verified** | Inspected upstream code at an identified commit demonstrates the relevant implementation. It does not establish runtime behavior of the assembled stack. |
| **Documented** | Official documentation describes the capability; live documentation can be ahead of the inspected release. |
| **Historical live evidence** | Existing ProxyLens tests or experiments exercised the specified old runtime/path, with the limitations recorded in repository evidence. |
| **Proposed** | An architectural choice or acceptance condition recommended here, not an existing upstream guarantee. |
| **Unverified** | Requires the new POC or a product decision. |

### 2.2 Research snapshots

| Component | Snapshot used | Qualification |
|---|---|---|
| LiteLLM | `v1.106.6`; release published `2026-10-28T23:03:09Z`; commit `61c6ab78393ef45683dd7d963d2a315bd845e20b` | Reported as latest non-prerelease during the October 29 research. This is a dated observation, not a rolling deployment recommendation. [LL-release] |
| Sub2API | `v0.2.18`; October 23, 2026; commit `ac1b8f1271be0d674fa6f074403c1410f30a3a81` | Release inspected during October 28 comparison. [SUB-release] |
| New API | `v1.0.0-rc.47`; October 25, 2026; commit `e835b1bfc43b565d625537830dbfb19328925134` | GitHub reported `prerelease:false` despite the RC name. Main-only changes are distinguished in the comparison. [NEW-release] [alternatives] |
| CLIProxyAPI | `v8.0.40` | Current exercised provider runtime; image digest is in [dependency pins](../dependency-pins.md). |
| CPAMP Full Mode | `v1.14.9` | Current exercised collector/history runtime; image digest and read-contract limits are recorded locally. |
| Langfuse | `v4.69.0` in existing exporter experiments | Historical evidence for those experiments, not a verified LiteLLM/Langfuse version pair. See [exporter evidence](../exporter.md). |

The POC must pin the actual LiteLLM image digest, database schema, callback/SDK
dependencies, CPA version and Langfuse destination version. A source tag alone
does not identify every deployed dependency. No new LiteLLM image was installed
or digest-verified in this handoff.

### 2.3 What the current system has actually proved

The existing live acceptance record covers non-streaming, streaming, function-tool
and synthetic-image requests through the current ProxyLens gateway and the pinned
CPA/CPAMP pair. Successful cases established native correlation for that path;
the recorded cancellation case did not establish a durable CPAMP usage event.
These observations do not transfer automatically to LiteLLM in front of CPA.
[live-acceptance]

The current tenant projection remains disabled because the required independently
reviewed correlation and durable-history artifacts are incomplete. Successful
requests do not establish retry/failover attribution, cancellation completeness,
retention/restart coverage or tenant isolation. See [live acceptance](../live-acceptance.md)
and [projection completeness](../projection.md).

## 3. Why LiteLLM is now the first recommendation

| Candidate | Strength for this requirement | Main remaining work | Position |
|---|---|---|---|
| **LiteLLM → CPA + Langfuse** | Native user-owned keys and personal spend; scoped usage APIs; documented hooks; existing Langfuse integrations; retains exercised CPA runtime. | Prove actual clients, complete metering and budget behavior; implement missing personal panels; settle reporting authentication. | **First POC.** [lite-assessment] |
| Native Sub2API | Subscription OAuth and forwarding plus a detailed personal dashboard in one product; CPA is not required. | Separate reasoning-token persistence and user-attributed Langfuse integration; test outage accounting and client compatibility. | Strong alternative if integrated subscription/dashboard UX is the overriding priority. [alternatives] |
| New API → CPA | Native users, keys, quota and consumption dashboard while retaining CPA. | Personal performance/error aggregation, ordinary-text reasoning persistence, Langfuse integration and relay compatibility. | Alternative if New API's quota/product model is preferred. [alternatives] |
| Native New API Codex | Direct Codex OAuth channel exists. | Same analytics/export work; direct provider behavior needs comparison with CPA. | Possible narrower deployment when its supported provider path suffices. [alternatives] |
| Current custom ProxyLens stack | Explicit group/application policy, lineage and conservative CPAMP-derived projections already exist. | Personal ownership is a contract change; personal dashboard still needs work; substantial custom identity/projection surface remains. | Preserve evidence and useful contracts; less direct fit for the clarified personal product. [gateway-contract] [projection-contract] |

The recommendation minimizes the **kind** of custom code required: reporting
rather than another OAuth runtime, general gateway, key-management service and
Langfuse transport. It does not claim that LiteLLM has every CPAMP panel, that two
gateway hops are free, or that its spend logs are already proven lossless.

Specific alternative findings worth preserving:

- Sub2API's inspected usage schema retains reasoning effort, not a separate
  reasoning-token measurement. PR #7912 was open/unmerged on October 28, 2026;
  that status must be rechecked before a future implementation decision.
- The inspected community Sub2API Langfuse integration used provider-account
  `userId` and full-content capture. It is not suitable unchanged for personal,
  metadata-only attribution.
- New API's ordinary text settlement path did not retain the full usage object
  or separate reasoning count. Its task-provider plugin API is not a universal
  dashboard or ordinary-request telemetry hook.
- Neither inspected upstream alternative demonstrated a native Langfuse exporter.
  These are bounded findings for the recorded snapshots, not permanent claims.

The [alternatives comparison](new-api-stack-comparison.md) contains the pinned
source evidence and operational qualifications for these findings.

## 4. Proposed ownership and identity contracts

### 4.1 Separate three kinds of authority

| Domain | Proposed authority | What it does not establish |
|---|---|---|
| Platform access and client-facing accounting | LiteLLM user/key records, admitted requests, persisted usage/spend and budget state | The actual provider subscription invoice; every hidden CPA retry or credential choice. |
| Provider execution and optional operator history | CPA provider runtime; CPAMP history if enabled | Which platform user owns a shared CPA service credential's traffic without explicit correlation. |
| Observability | Langfuse observations | Authorization, quota settlement, complete request history or personal data isolation merely from a `userId` filter. |

“Accounting authority” here means the selected platform source for user-facing
usage and allowance decisions. Whether it meets the desired durability and
completeness contract is an adoption gate. Do not call it an authoritative provider
billing ledger. Do not add CPAMP and LiteLLM request totals as if they represented
independent user consumption.

### 4.2 User-owned keys

Recommended baseline:

1. Each person receives a stable LiteLLM internal user ID.
2. Each IDE/application uses a distinct key owned by that user.
3. Ownership is resolved from authenticated server-side key state at admission.
4. Personal totals aggregate all keys belonging to that user, including retained
   historical usage from rotated or revoked keys.
5. Record the admitted owner in historical request facts. Renaming or deleting a
   key must not silently change historical attribution.

LiteLLM documents `internal_user` for own-key management and own spend, and
`internal_user_viewer` for read-only personal keys/spend. **`proxy_admin_viewer`
is not a personal read-only role:** it can see other users' keys/spend. Extra team
permissions can also broaden visibility. [LL-self-serve] [LL-scopes] [LL-spend]

The historical-ownership and lifecycle rules above are proposed acceptance
requirements. Their exact behavior under the selected LiteLLM version still needs
testing rather than inference from the existence of a `user_id` column.

### 4.3 Ownership is not proof of a human at the keyboard

The current ProxyLens contract deliberately leaves the human subject null for
machine-key requests and does not attribute them to the key creator. See
[the gateway contract](../gateway.md) and [exporter identity rules](../exporter.md).

The proposal changes the reporting meaning: a machine request using a personal
key is attributed to its **platform owner**, even without an interactive human
login for that request. This supports “my usage” but does not prove who physically
used the credential. Record an attribution basis such as `key_owner`; keep a
verified interactive actor, if present, separate. Existing exporter code cannot
simply be relabeled to make this change.

Shared application/team keys do not identify each human behind them. Initially
prefer user-owned keys. If shared services are later required, define either a
service owner or a trusted application-to-user delegation contract. Never infer
personal ownership from arbitrary request-body `user`, customer headers, email,
key display name or shared CPA credential. LiteLLM customer/end-user attribution
is separate from platform-user identity. [LL-customer] [LL-payload]

### 4.4 Reporting authorization

Native daily-activity code resolves ordinary callers to their authenticated user
and rejects another user's ID. Log routes enforce user/authorized-team scope.
This is source evidence of backend scoping, not just a filtered sidebar.
[LL-user-api] [LL-scopes] [LL-spend]

A custom reporting backend must:

- Derive the user from a validated session; apply scope before query/aggregation.
- Apply the same scope to totals, details, search, export and session views.
- Include user scope in response-cache keys and reject mismatched object owners.
- Keep any privileged upstream read credential server-side.
- Treat the browser's requested user/key IDs as filters subject to authorization,
  never as proof of ownership.

**Unresolved implementation seam:** how a separate reporting UI obtains a trusted
LiteLLM-user session. Native login is the baseline for native Usage; it is not
proof of a supported cross-application login/token exchange. The POC must select
and demonstrate a supported session integration. Do not assume an inference key,
dashboard login token and plugin claim are interchangeable credentials.

### 4.5 Limits and allowance

LiteLLM documents virtual-key budgets and rate limits. The desired policy still
needs to specify user-versus-key limits, reset periods, model restrictions,
concurrency and failure behavior. In particular, identify whether budgets are
strict reservations or asynchronously updated spend checks, and quantify allowed
overshoot. Do not promise strict never-overspend semantics from feature names.
[LL-editions] [LL-rbac]

## 5. Dashboard: native baseline and custom scope

The following capability observations refer to the inspected release and official
documentation. All panels must be exercised with ordinary users against the
selected CPA upstream before being accepted as product behavior.

| Personal capability | Native evidence | Proposed remaining work |
|---|---|---|
| Login, own keys and own spend | Internal-user self-service. [LL-self-serve] | Verify onboarding, roles, key lifecycle and account disablement. |
| Request/token/spend totals | Personal activity and model/key views. [LL-activity] | Validate totals across time ranges, pagination, budget resets and key rotation. |
| Input/output/total tokens | Activity charts and request detail. [LL-activity] [LL-detail] | Validate CPA usage preservation and subset semantics. |
| Cache-read/write tokens | Native charts/details. [LL-activity] [LL-detail] | Separate provider prompt cache from gateway response-cache hits. |
| Reasoning tokens | Request detail when supplied; no dedicated daily-user reasoning aggregate verified. [LL-detail] [LL-schema] | Retain usable request fields and build a personal time series if required. |
| Estimated cost | Native spend and request breakdown. [LL-activity] [LL-detail] | Set explicit model prices, pricing version and subscription-cost labels. |
| Success/failure | Activity charts and error details. [LL-activity] [LL-detail] | Prove coverage of upstream failures, semantic stream errors, cancellation and admission rejection. |
| Average latency | Native activity metric; inspected daily mean uses timed successful requests. [lite-assessment] [LL-schema] | Label the population; do not mix failed/untimed requests into an undocumented denominator. |
| Total duration and TTFT | Request details and timing fields. [LL-detail] [LL-payload] | Validate stream timing; add personal p50/p95/p99 if needed. |
| Heatmap | Full personal CPAMP-style parity not verified. | Aggregate retained scoped events with a declared timezone/bucket width. |
| Measured RPM/TPM | Limits and daily totals exist; personal minute-series not verified. | Derive measured throughput from timestamped events; distinguish it from configured limits. |
| Request filtering/export | Scoped log/activity APIs exist. [LL-user-api] [LL-spend] | Verify edition gates, retention, page completeness and export authorization. |
| Provider-account health/quota | CPA/CPAMP operator capability. | Keep optional and operator-only; correlate explicitly if needed. |

### Suggested delivery order

1. **First usable personal experience:** native login, personal keys, totals,
   history, model/key/date filters and tested access/limit behavior.
2. **Targeted reporting additions:** reasoning/cache trends, latency/TTFT
   percentiles, heatmaps and measured throughput only where required and supported
   by persisted data.
3. **Optional integration polish:** embedded UI, branding, provider diagnostics
   and richer session navigation after the backend contract works.

This is a proposed ordering. If a missing metric is essential to the user's
definition of “CPAMP-like,” it becomes a first-release acceptance gate.

### Native APIs versus an additional store

Start with self-scoped native activity and log APIs. The research identified
`/user/daily/activity`, `/user/daily/activity/aggregated` and `/spend/logs/v2`,
plus related detail/export routes. The paginated daily API was marked BETA in
source. Daily historical spend and a resettable running user-spend counter are
not interchangeable. Pin and test each selected endpoint. [LL-user-api] [LL-scopes]
[LL-spend]

Add a reporting store only when required fields or aggregates cannot be obtained
reliably from retained native data. Prefer a supported read interface; a direct
database read, if chosen, is an explicit version-coupled, read-only adapter.
Callbacks can capture otherwise missing fields, but callback existence alone does
not provide durable replay. Section 6 defines the required distinction.

## 6. Proposed request-accounting and reporting data contract

This section is a design input for the revised specification, **not a claim that
LiteLLM already exposes one endpoint or table with this schema**.

### 6.1 Request identity and attempt identity

Count one client model invocation as one logical request. Record LiteLLM retries
and deployment attempts separately. CPA can make additional hidden provider
attempts; do not invent them from LiteLLM callbacks. The inspected logger exposes
distinct request-level and deployment-attempt failure hooks. [LL-callback]

Choose and prove a stable persisted request/event identity. Namespace it by
deployment/source instance. Do not assume a caller-provided ID is unique, or that
list position, timestamp plus model, and a provider-account ID are safe dedup keys.
If more than one event updates a request, define revision/finality rules and
idempotent aggregation. Re-reading a window must not count the request twice.

### 6.2 Minimum fields

| Field family | Proposed facts and rules |
|---|---|
| Identity | Source instance, stable request/event ID, owner user ID, stable non-secret key ID, optional application label, attribution basis, schema version. |
| Correlation | LiteLLM request ID, safe upstream CPA ID if observed, optional CPAMP event ID, trace/session IDs, explicit missing/ambiguous status. |
| Route | Requested model/alias, configured upstream deployment, observed response model/provider where available; configured route is not proof of provider credential selection. |
| Time | UTC start, first-token and terminal timestamps; explicit units; nullable unknown fields. |
| Outcome | Success, failure, cancelled, timeout or unknown; HTTP status and sanitized error category; separate admission rejection and provider-attempt events. |
| Usage | Original numeric usage fields and provenance, exclusive normalized buckets, normalization version, completeness/quality and estimate flags. |
| Cost/allowance | Amount, currency, pricing version/source and estimate classification; internal allowance consumption kept separate. |
| Collection | Persisted/observed time, source checkpoint or bounded scan window, last-success time, freshness and known gaps. |

Store raw **usage measurements**, not raw prompts, response bodies, credentials or
arbitrary inbound metadata. Capture only fields needed by the contract. LiteLLM's
standard callback payload documents owner metadata, timing and optional
`usage_object`; its presence in a callback does not prove database retention.
Metadata filtering can also remove historical details. [LL-payload] [LL-logs]

### 6.3 Token normalization

Preserve source values separately. Where a verified provider contract says cache
counts are subsets of input and reasoning is a subset of output, derive exclusive
buckets once:

```text
uncached_input     = inclusive_input - cache_read - cache_write
nonreasoning_output = inclusive_output - reasoning
exclusive_total    = uncached_input + cache_read + cache_write
                   + nonreasoning_output + reasoning
```

These equations are conditional, not a universal provider schema. Cache-write
semantics and absent fields differ by source. Require nonnegative consistent
values; preserve unknowns as unknown and reject inconsistent normalization.
Do not treat absent reasoning/cache data as measured zero or add reasoning on top
of an already-inclusive output total.

For a proven input of 100, cache read of 20, cache write of 0, output of 40 and
reasoning of 10, the exclusive buckets are **80 / 20 / 0 / 30 / 10**, total **140**.
The current CPAMP adapter has additional source-specific transformations; its
normalizer must not be reused unchanged for LiteLLM response usage.
[cpamp-contract]

### 6.4 Timing, throughput and outcomes

- Total duration is terminal time minus start time.
- TTFT is first-token time minus start time when that measurement exists.
- LiteLLM's documented streaming `response_time` can mean TTFT; do not label it
  total duration without validating the path. [LL-payload]
- Define whether RPM uses admission or completion time, whether TPM assigns all
  tokens at completion, and whether idle minutes appear as zero. A configured
  rate limit is not a measured traffic series.
- Compute percentiles over comparable request samples, not averages of daily
  percentiles. Declare the successful/failed/streaming population and timezone.
- A 200 response that terminates with an SSE error is not automatically a
  successful generation. A disconnected request with no final usage is unknown
  consumption, not a known zero-cost failure.
- Keep HTTP attempts, accepted model invocations and rejected admissions in
  separately labeled counters before defining a success-rate denominator.

### 6.5 Cost has three different meanings

1. **Estimated API-equivalent cost:** usage multiplied by a selected model-price
   table; store its version and currency.
2. **Internal allowance consumption:** the gateway's budget/quota accounting;
   it may deliberately use a different price or unit.
3. **Actual subscription expenditure:** the provider's subscription invoice;
   a per-request token estimate is not this invoice.

Unknown model pricing must not silently become a credible zero-cost request.
Dashboard and Langfuse labels must preserve these distinctions. Cache/reasoning
cost breakdowns can be subsets of an inclusive total; avoid adding them twice.
[LL-payload] [lite-assessment]

### 6.6 Durability, replay and freshness

Prefer LiteLLM's persisted request records as the reporting source. An additional
store should be a rebuildable projection of those records wherever they retain
the required data. Test pagination, bounded windows, overlap, stable deduplication,
retention and restart behavior before asserting rebuild equivalence.

If a desired field exists only in a transient callback, capturing it creates a new
durability dependency. Decide explicitly whether best-effort availability is
acceptable or whether a supported durable capture/replay mechanism is necessary.
Do not call callback-only data rebuildable after the source has discarded it.

Proposed reporting states are available, stale, degraded and unavailable, with
last-success time and known coverage gaps. A healthy process or successful last
poll does not prove complete history. Native spend persistence and admission/budget
state must also be tested for divergence during crashes and database outages.

**Suggested POC freshness target:** personal records/totals visible within 60
seconds under normal operation, with the actual lag measured. This is a proposed
product target, not an upstream guarantee. Retention and crash-loss tolerance must
be agreed separately.

## 7. Custom dashboard integration and edition boundaries

### 7.1 Recommended initial shape

Use native personal Usage first. For missing panels, prefer a separate authenticated
reporting UI/backend. It can later be embedded once the normal-user session and
data-access paths are proven. Keep custom work behind a small adapter rather than
forking all of LiteLLM's UI, authorization and forwarding.

### 7.2 What plugins actually provide

The verified plugin framework embeds a complete independently hosted application
with its own backend, manifest and UI. It is not an arbitrary panel-injection API
for the native Usage screen. The identity claim contains `plugin`, `user_id`,
`user_role` and `exp`; it does not contain a LiteLLM bearer credential or confer
analytics authorization by itself. [LL-plugins] [LL-plugin-source]

There are two important access limitations in the inspected release:

1. `/plugin-proxy/{name}/{path}` forwards **to the plugin backend** and requires
   `proxy_admin`; it is not delegated ordinary-user access to LiteLLM analytics.
2. Central ordinary-user allowlists omit plugin discovery/auth-token routes.
   This is a **static-source concern**, not a completed runtime finding about all
   possible configurations. Test it before committing to an embedded personal UI.

Do not solve this by giving personal users administrator roles. A plugin still
needs its own trusted session and scoped data access. The docs' stated `v1.89.3`
minimum was not independently confirmed; presence was verified in `v1.106.6`.
[LL-plugin-source] [LL-route-checks] [LL-route-types] [lite-assessment]

### 7.3 OSS and Enterprise findings

These are dated feature-gate observations, not guarantees for future releases.
Verify the chosen image and applicable license before adopting a gated dependency.

| Capability | Research finding |
|---|---|
| Admin UI, virtual keys, basic spend, budgets/rate limits | Listed as OSS; personal internal-user views are documented and source-scoped. [LL-editions] [LL-self-serve] |
| Native password/invitation login | Proposed baseline; distinct from SSO. [LL-self-serve] |
| Dashboard SSO | Documented free allowance up to five users; Enterprise beyond that. This is not a general five-user limit on native accounts. [LL-sso] |
| Direct IdP-JWT gateway authentication | Separate premium check; not implied by the UI SSO allowance. [LL-jwt] |
| Delegated organization/team administration | Enterprise boundary; unnecessary for baseline personal ownership. [LL-editions] |
| `/global/spend/report` and scoped spend-report APIs | Premium checks exist; ordinary self-scoped daily activity is a different API. [LL-spend] [LL-user-api] |
| Dashboard plugin framework | No premium gate found in inspected implementation; files outside Enterprise carve-out. This does not resolve normal-user access or external plugin licensing. [LL-plugin-source] [LL-license] |

Recommendation: validate the native-account, personal-dashboard path without an
Enterprise license first. If the required custom reporting or SSO flow depends on
a premium interface, make that a visible product decision rather than a hidden
implementation assumption.

## 8. Langfuse integration contract

### 8.1 Reuse the existing integration

LiteLLM includes `langfuse` and `langfuse_otel` integrations; Langfuse's own guide
documents the latter. Select one supported path for the pinned SDK/destination and
test it. Avoid enabling duplicate exporters for the same logical request unless
the resulting observation hierarchy is deliberate. [LF-integration] [LL-langfuse-source]
[LL-langfuse-otel]

Asynchronous/background delivery is documented and present in source. It does not
prove a durable outbox, lossless crash recovery, exactly-once delivery or zero
latency impact. Measure end-to-end behavior and document the accepted delivery
contract. Langfuse failure must not cause a provider request to be replayed.

### 8.2 Trusted user and session attribution

- Map the trusted platform key owner explicitly to a stable, deployment-namespaced
  Langfuse `userId`; record the attribution basis as owner rather than interactive
  authentication where appropriate.
- Treat LiteLLM `user_api_key_user_id` and request `user`/customer metadata as
  different inputs. The documented `trace_user_id` default derives from the
  completion `user` argument; that is not automatically the desired owner.
- Accept a session/conversation identifier only under a defined trusted contract;
  namespace it by deployment and owner to avoid cross-user collisions. Otherwise
  use a per-request fallback and label it as such.
- Retain model/key/request correlation as bounded metadata. A CPA provider-account
  ID must never substitute for the platform user.

These mappings require a demonstrated server-side hook/configuration path, not
trust in caller-controlled metadata. [LL-langfuse-identity] [LL-payload] [LL-hooks]

### 8.3 Default payload and operational behavior

Default to metadata, model, status, original request timing, trusted user/session
IDs, usage quality and estimated cost. Disable prompt/output/tool-content capture
and inspect the actual emitted payload, including errors and stream paths.
LiteLLM documents message-redaction controls, but their coverage must be validated
for the chosen integration. Evaluate caller-controlled `no-log` behavior if
observation coverage is a requirement. [LL-logging]

Observations should report when usage is absent, partial or estimated. Export lag
must not replace model latency. Langfuse `userId` filtering is an observability
attribute, not sufficient isolation for a public personal dashboard.

### 8.4 Existing exporter lessons to preserve

The current ProxyLens exporter implements explicit payload freezing, uncertainty,
retry boundaries and redaction. Its Langfuse `v4.69.0` experiment found duplicate
visible observations during same-ID enrichment and an ambiguous accepted/malformed
acknowledgement case. This is version/path-specific evidence, not a blanket claim
that every LiteLLM integration duplicates observations. [exporter-contract]

Use those failure scenarios to test the native integration. If product requirements
demand durability beyond what it demonstrates, scope a narrow durable delivery
extension after identifying the actual gap. Do not carry the entire CPAMP/group
exporter forward merely because it exists; its identity and input contracts differ.

## 9. LiteLLM → CPA compatibility boundary

### 9.1 Source-supported composition, untested pair

The pinned LiteLLM OpenAI Responses adapter constructs `{api_base}/responses`.
That supports directing its OpenAI-compatible model route to CPA's internal
inference base. The CPA inference credential must be a service-owned credential,
separate from all end-user keys and CPA management credentials.
[LL-responses-source] [LL-responses]

Select a native Responses path for Responses clients. Do not assume translating
Responses into Chat Completions and back preserves all semantics. Configuration
must preserve the intended endpoint, requested model and CPA route; a working
non-streaming request is not proof of the rest of the client protocol.

Required compatibility inventory for the actual client includes:

- Non-streaming and SSE Responses, event order and terminal usage.
- Function/tool calls and tool-result continuation.
- Images and any other required multimodal input.
- Requested aliases, returned model names and model discovery.
- `previous_response_id` or client-managed history, if used.
- Errors before headers, semantic errors after headers, timeouts and disconnects.
- Ancillary retrieval/cancellation/files or WebSocket routes **if the actual client
  uses them**; these were not established by the LiteLLM dashboard research.

Record retry/fallback behavior at both gateways. Initially prefer a simple single
route with unnecessary fallback disabled so the POC can attribute each event.
Do not allow an interrupted stream to produce duplicate visible output through an
unexamined retry policy. Compatibility and latency remain unverified for this pair.

### 9.2 Correlation becomes optional enrichment, not personal ownership

Capture safe CPA response correlation where supported. Provider-account drill-down,
CPA-side retry reconciliation and CPAMP-derived supplements still require a proven
join. A shared service key, matching timestamp or matching model is not that join.

Basic personal usage should continue to work without CPAMP if LiteLLM has its own
verified owner and usage facts. Conversely, a LiteLLM cancellation record with no
final usage must not be filled with zero or guessed from nearby CPAMP rows.
The proposed design removes one dependency; it does not solve missing upstream
measurements by declaration.

### 9.3 Why keep CPA initially

Retaining CPA preserves the already exercised subscription runtime while changing
the user-facing management/reporting boundary. It avoids combining a gateway
replacement and a provider-runtime replacement in the first comparison.

LiteLLM's live subscription documentation also describes direct Claude, Codex and
Copilot flows. During this research it labeled Codex `v1.109.0+` and Copilot
`v1.108.0+`, beyond the inspected `v1.106.6` release. Do not describe those later
documented paths as verified stable features of this snapshot, or assume equivalence
to CPA account pooling. A future CPA-removal evaluation is a separate decision.
[LL-subscriptions] [lite-assessment]

## 10. Deployment and operational implications

### 10.1 Proposed single-host topology

Retain Docker Compose as the reference deployment. A revised stack would contain:

| Service/state | Proposed disposition |
|---|---|
| LiteLLM and its persistent database | Required for the proposed platform/user/key/spend boundary; pin image, schema and migrations. |
| CPA config and authorized provider credentials | Retain persistent state and server-side credential handling. |
| Reporting service/store | Add only for approved gaps; separate schema/permissions from upstream-owned state. |
| Redis or other coordination dependency | Include if required by the selected LiteLLM rate-limit/cache/deployment configuration; determine and test rather than assume. |
| Langfuse | Select a compatible existing deployment or explicitly package its dependencies. Record version, storage and retention ownership. |
| CPAMP | Optional operator profile; persistent history if retained; exactly one consumer for each CPA queue. |
| Keycloak and current custom API/gateway/worker | Remain part of the current stack until an approved migration; not required in the proposed native-account baseline. |

The current [Compose file](../../compose.yaml) includes Keycloak, CPA, CPAMP,
PostgreSQL and the custom API/gateway/worker. Langfuse is currently configured as
an external compatible endpoint, not bundled with its databases. The proposed
diagram must not be mistaken for what the checked-in Compose already starts.
[dependency-pins]

### 10.2 Operational contracts to carry forward

- Expose only intended client/UI ingress; keep CPA management, CPAMP manager,
  databases and service credentials private.
- Retain mounted secrets or an equivalent server-side secret source. Provider
  OAuth files, upstream inference credentials and Langfuse credentials are not
  browser configuration.
- Back up user/key ownership, budget state, spend history, CPA credentials and
  any reporting-only measurements. Record schema/version dependencies for restore.
- Separate API readiness from reporting freshness and Langfuse delivery health.
  Optional CPAMP/Langfuse outages should not make a healthy CPA inference route
  unavailable merely because monitoring is stale.
- Specify behavior for LiteLLM database/coordination outages: whether admission
  stops, which cached authorizations remain valid, how revocation propagates and
  whether unrecorded usage is possible. The current custom fail-closed behavior
  must not be assumed to exist unchanged in LiteLLM.
- Document upgrade order and rollback compatibility. A binary rollback may not
  reverse a database migration or restore accounting state.

These are proposed operational requirements, not runtime guarantees of the
replacement stack.

### 10.3 Retention and capacity decisions

Existing issue #6 proposes 90 days for request/projection data, 365 days for
audit/security events and 90 days for Langfuse metadata. Treat them as starting
policy values to confirm, not proof that any replacement component implements
them by default. Distinguish request retention from query-range limits and budget
reset periods.

Specify reporting granularity, expected users/keys, request rate and history size
before estimating capacity. Measure request latency/TTFT with and without LiteLLM,
and with telemetry enabled/disabled or unavailable. No benchmark, throughput
ceiling or production-sizing result was produced by this research.

## 11. Current-work disposition and specification delta

### 11.1 Existing work to retain, adapt or retire later

“Retire” below is a proposed future disposition after replacement acceptance;
it is not an instruction to delete current work during the research handoff.

| Existing area | Files to inspect | Proposed disposition and reason |
|---|---|---|
| CPA deployment/runtime | `compose.yaml`, `deploy/cliproxyapi/`, `docs/dependency-pins.md` | Retain provider boundary and pin/evidence discipline; adapt ingress networking. |
| Native lineage and protocol testing | `src/proxylens/lineage.py`, `src/proxylens/correlation.py`, `docs/correlation.md`, `scripts/live-acceptance.py`, `tests/test_gateway.py` | Reuse acceptance scenarios and correlation lessons; adapt IDs and test client entrypoint. Old tests are not replacement-stack proof. |
| Custom gateway | `src/proxylens/gateway.py`, `src/proxylens/policies.py`, `docs/gateway.md` | Replace broad forwarding/admission responsibility with LiteLLM if accepted; preserve explicit compatibility and failure requirements. |
| Keycloak identity/group integration | `src/proxylens/identity.py`, `src/proxylens/oidc.py`, `src/proxylens/keycloak.py`, `src/proxylens/resource_identity.py`, `deploy/keycloak/`, `docs/identity.md` | Remove from the proposed baseline after adoption; retain historical evidence. Revisit only if SSO/group requirements return. |
| Applications and custom key lifecycle | `src/proxylens/resources.py`, `src/proxylens/resource_routes.py`, `docs/resources.md` | Prefer native user-owned virtual keys and application labels; explicitly compare key storage, reveal, rotation and revocation guarantees. |
| CPAMP read adapter | `src/proxylens/cpamp.py`, `docs/cpamp-contract.md`, `tests/test_cpamp.py` | Retain if optional diagnostics/reconciliation need it. Remove from the critical path for personal totals. |
| Group-scoped usage projection | `src/proxylens/projection.py`, `src/proxylens/projection_routes.py`, `src/proxylens/projection_settings.py`, `docs/projection.md` | Replace ownership/source contract. Reuse missing-data, normalization, replay and freshness lessons, not its CPAMP schema blindly. |
| Custom Langfuse exporter | `src/proxylens/exporter*.py`, `docs/exporter.md`, `tests/test_exporter.py` | Prefer native integration first. Preserve failure/redaction fixtures; adapt narrow durability code only if the POC proves a need. |
| Runtime and operations | `src/proxylens/runtime.py`, `src/proxylens/operations*.py`, `src/proxylens/config.py`, `docs/operations.md`, `docs/deployment.md` | Rework health, backup, retention and outage ownership around the selected services. |

Do not plan a database migration by renaming group IDs to user IDs. Existing
machine requests do not prove personal ownership. Preserve old history under its
original contract or explicitly label a new accounting epoch; migrate ownership
only where authoritative mapping exists. Likewise, do not assume hashed current
client keys can be imported into a new key system; plan reissuance if required.

### 11.2 Explicit specification changes

| Current contract | Proposed revision |
|---|---|
| Keycloak is mandatory human/group authority. | Native LiteLLM users are the baseline; external SSO is optional and separately evaluated. |
| Group → application → client key is the canonical ownership chain. | User → user-owned virtual keys is the personal ownership chain; application identity can initially be a label. |
| Custom ProxyLens gateway owns admission and forwarding. | LiteLLM owns the client-facing gateway; custom code is limited to demonstrated integration/reporting gaps. |
| Every personal/tenant usage row derives from CPAMP. | LiteLLM client-request records supply personal usage; optional CPAMP history describes provider-side execution. |
| CPAMP join proof gates all tenant usage. | Verified LiteLLM ownership, metering and isolation gate personal usage; CPA/CPAMP join proof gates only dependent enrichment. |
| Machine requests have no human `userId`. | Owner-attributed usage may use platform-owner `userId`, explicitly distinguished from a verified interactive actor. |
| Custom lineage/CPAMP exporter supplies Langfuse. | Native LiteLLM integration with explicit trusted mappings and measured delivery semantics. |
| Hard budgets are excluded pending CPAMP freshness. | Decide required LiteLLM limit/budget semantics and test concurrency/outages independently of CPAMP. |
| Usage is a group-scoped rebuildable projection. | Define the retained client-request source, additional capture if any, and exactly which personal views are rebuildable. |

The owner should revise [ADR 0001](../adr/0001-architecture-boundaries.md),
[GLOSSARY.md](../../GLOSSARY.md), [AGENTS.md](../../AGENTS.md),
[issue-tracker guidance](../agents/issue-tracker.md), README and relevant component
docs together when adopting the new boundary. The glossary especially needs to
distinguish platform user, customer label, provider account, key owner, interactive
actor, client request, provider attempt, spend estimate and allowance consumption.
This handoff leaves those authoritative documents unchanged.

### 11.3 Suggested migration sequence

1. Approve a scoped experimental POC specification with required features and
   acceptance thresholds; draft the successor ADR and glossary changes as
   proposals. This authorizes the candidate experiment without superseding the
   current deployment's authoritative contracts.
2. Build the isolated POC with new native users/keys and the pinned CPA boundary.
3. Run the applicable gates and decide whether the candidate is viable. Record
   failures and missing reporting/authentication/persistence capabilities. A
   conditional decision to continue is not final architecture adoption.
4. Implement the bounded gaps required by the selected product scope. Retest
   affected cases and resolve every remaining required gate. Optional embedding
   or provider diagnostics need not pass if excluded from that scope.
5. Once all required acceptance evidence passes, approve the successor ADR/spec,
   glossary and repository guidance together. This is the point at which the
   corresponding old contracts become explicitly superseded.
6. Execute the separately approved cutover with key issuance, historical-data
   handling, backups and rollback. Do not replay production model requests merely
   to compare metering.
7. Retire superseded custom components only after replacement acceptance and
   cutover validation. Preserve original experiment records and source pins.

## 12. Focused POC and adoption gates

All cases in this section are **proposed and unperformed for LiteLLM → CPA**.
Existing CPA/CPAMP or exporter evidence does not mark them passed.

### 12.1 Fixture and evidence package

Use two ordinary users, A and B, with at least two user-owned keys each; one
administrator for setup; one shared service-owned CPA inference credential; the
existing authorized provider runtime; and a separate Langfuse test project.
Test both relevant ordinary-user roles. Keep optional team permissions absent
initially so they cannot mask the intended own-only boundary.

Record image digests, source/config revisions, edition/license state, model route,
database/schema versions, client version, callback settings and test time. For
each synthetic request, capture a safe manifest linking the client result,
LiteLLM persisted event, dashboard read and Langfuse observation, plus CPAMP only
where needed. Keep secrets and raw content outside committed evidence.

### 12.2 Acceptance matrix

| Gate | Exercise | Pass evidence / failure consequence |
|---|---|---|
| **P1 — Actual client compatibility** | Nonstreaming, SSE, tools with continuation, images, aliases and every protocol/ancillary endpoint actually used by the chosen IDE/SDK. | Correct client-visible semantics and native route; no dropped required fields or unintended buffering/replay. Any required unsupported route blocks adoption. |
| **P2 — Personal isolation** | A requests B's user/key IDs, request details, sessions, exports and filtered totals; vary URL/body/header IDs and cached responses. Repeat in both ordinary-user roles. | No B data or cross-user aggregate leakage. Use backend evidence, not only UI visibility. Failure blocks personal deployment. |
| **P3 — Key/owner lifecycle** | Multiple keys per user, key rename/rotation/revocation/expiry, user disablement, model restrictions, forged customer/owner metadata. | Historical ownership remains stable; forbidden requests do not reach CPA; revocation/disablement propagation is measured and meets the chosen bound. |
| **P4 — Metering and tokens** | Known input/output usage, cache read/write where supported, reasoning, missing usage, failures, retry/fallback and cancelled streams. | Reconcile response usage, persisted logs and scoped totals; no double-counted requests/subsets. Unknowns and estimates remain labeled. Essential fields lost before persistence require a capture change. |
| **P5 — Budget and rate behavior** | Per-key and aggregate-user exhaustion, resets, concurrent requests, long streams, failures and database/coordination outages. | Document enforcement point, overshoot and recovery; meet agreed limits. Do not call approximate spend checks strict reservations. |
| **P6 — Dashboard usefulness** | Both users view totals/history, filters, cache/reasoning details, latency and TTFT. Compare required panels against the section 5 matrix. | Product owner can accept the native baseline or precisely identify additional panels/data. Missing mandatory panels block the relevant product milestone. |
| **P7 — Read/rebuild contract** | Pagination over more than one page, overlapping windows, key rotation, budget reset, restart, retention and deliberately interrupted reads. | Stable deduplication and equivalent rebuild for retained source facts; report freshness/gaps. Do not treat pagination success as complete source coverage. |
| **P8 — Crash and persistence behavior** | Stop/restart gateway or collector around terminal usage; interrupt database writes and callback delivery using synthetic traffic. | Quantify missing/duplicate records and spend/log divergence; meet explicit tolerance or add narrow durable capture. No hidden claim of crash safety. |
| **P9 — Langfuse attribution/redaction** | Normal, streaming, failed and cancelled requests from both owners; forged `user`/trace/session metadata; content-bearing tool/image cases. | Owner/session mapping is trusted, no secrets or prompt/output content appear by default, usage/cost semantics match the contract. |
| **P10 — Langfuse delivery/outage** | Slow/unavailable sink, restart before flush, timeout after possible remote acceptance and duplicate callback configuration. | Provider response path remains usable; measured delivery/loss/duplicate behavior documented; no provider replay. Durable delivery requirements must be proved separately. |
| **P11 — Reporting login and edition** | Native accounts without Enterprise, selected scoped APIs and any separate UI login/session flow. If embedding is proposed, test plugin discovery/claim/backend access as ordinary users. | A supported authenticated path works without admin credentials in browsers. Identify paid dependencies or unsupported embedding before committing to that UI shape. |
| **P12 — Optional CPAMP independence** | Disable CPAMP, then test healthy LiteLLM/CPA requests and personal reads; restore CPAMP and inspect optional diagnostics. | Personal ownership/totals do not depend on a CPAMP join. Only CPAMP consumes its queue; diagnostic gaps remain explicit. |
| **P13 — Operations and performance** | Backup/restore, compatible upgrade/rollback rehearsal, telemetry outage, agreed concurrency/load and baseline CPA comparison. | Restored ownership/accounting works; health distinguishes inference/reporting/export; measured overhead and freshness meet agreed thresholds. |

### 12.3 Decisions needed before declaring a pass

Proposed gates need quantitative limits, not only green screenshots:

- Personal-report freshness target; suggested starting value is 60 seconds.
- Acceptable user/key revocation delay and budget overshoot under concurrency.
- Whether usage loss after process failure is forbidden or bounded and disclosed.
- Whether Langfuse delivery is best-effort or requires durable retry/recovery.
- Required latency/TTFT percentiles, their populations and overhead allowance.
- History retention, export range and supported user/request volume.

Core adoption requires actual-client compatibility, personal isolation, usable
native account/key management, trustworthy metering semantics and accepted limit
behavior. Langfuse and every dashboard feature included in the revised product
scope must pass their own gates. Optional plugin embedding and CPAMP enrichment
should not become mandatory dependencies accidentally.

If the chosen native account path and required scoped reports cannot work within
the accepted edition/cost constraints, or the required usage fields cannot be
retained reliably without broad gateway changes, revisit the candidate ranking.
Use the same fixtures for Sub2API/New API rather than switching on screenshots
or assuming fewer services guarantees better correctness.

## 13. Existing issue map and proposed follow-up work

### 13.1 Existing issues #1–#10

The issue bodies were read during handoff preparation on October 29, 2026. All ten
were OPEN then, despite substantial implementation and evidence in this repository.
Open issue state is not evidence that no code exists. No issue was edited, closed
or created as part of this handoff.

Prefer preserving implemented issue history and linking successor work where the
contract changes materially. Use the existing issue structure: problem/outcome,
scope, dependencies, testable acceptance, non-goals and operational notes.
[issue-guidance]

| Issue | Existing scope | Suggested owner action when revising the plan |
|---|---|---|
| **#1** Phase 1 POC | Keycloak/group/custom gateway, CPA/CPAMP correlation, projection and exporter. | Create a successor personal-usage POC parent or explicitly rebaseline the parent. Replace one-group fixture with two personal users; require P1–P13 according to selected scope. Preserve old evidence and unfinished gates. |
| **#2** Compose foundation | Keycloak, custom services, CPA, CPAMP, PostgreSQL and secrets. | Preserve foundation work; add a candidate deployment issue for LiteLLM/database, optional reporting/CPAMP and external-or-bundled Langfuse choice. New pins and health contracts required. |
| **#3** Request correlation | Deterministic custom gateway → CPA → CPAMP join gates tenant usage. | Retain the original evidence and limitations. Move basic ownership to LiteLLM; make CPA/CPAMP correlation a separate diagnostic-enrichment requirement. Do not mark the old join proof complete by changing architecture. |
| **#4** CPAMP read/export | Supported durable-history adapter and normalization. | Retain as optional diagnostics integration. Remove it as a prerequisite for every personal row; keep source omissions and version coupling documented. |
| **#5** Keycloak | OIDC, roles, group scope and reconciliation. | Preserve completed identity work; remove from baseline successor requirements. Replace product need with native account/role/onboarding acceptance. Evaluate SSO only if requested. |
| **#6** Operations | Retention, audit, backups, outages, freshness and recovery. | Rebaseline service ownership and failure behavior. Verify native key/audit/spend facilities rather than assume every custom guarantee exists. Include budget-state persistence, telemetry loss and optional CPAMP outages. |
| **#7** Custom gateway | Client-key auth, group/application policy and Codex forwarding. | Preserve compatibility scenarios; create a LiteLLM → CPA compatibility/configuration issue. Avoid maintaining two independent public admission/accounting layers without a specific need. |
| **#8** Langfuse exporter | Custom lineage/CPAMP input, Keycloak identity, durable retry and metadata-only export. | Create native-integration validation/adaptation work. Revise owner/session semantics explicitly. Preserve delivery/redaction tests; only require a custom outbox if product policy and POC justify it. |
| **#9** Resource/policy management | Group-owned applications and custom hashed client keys. | Replace baseline ownership with native users/virtual keys. Compare immediate revocation, reveal/storage and policy semantics; model gaps as explicit follow-ups instead of assuming equivalence. |
| **#10** Group usage projection | CPAMP-derived group/application history and proof-gated reads. | Create personal reporting/data-contract successor work using LiteLLM retained facts. Preserve normalization, unknown coverage and replay principles; replace source and ownership assumptions. |

Issue locations are recorded in the source register below. These are recommended
revisions, not edited tickets or claims that the existing acceptance criteria passed.

### 13.2 Independently testable successor work packages

The labels below are proposed planning identifiers, **not newly created GitHub
issue numbers**. Split or combine only after the POC determines actual gaps.

| Work package | Outcome and scope | Dependencies | Minimum acceptance evidence |
|---|---|---|---|
| **W1 — Define candidate boundaries and acceptance** | Approve the experimental POC specification; draft proposed ADR/glossary changes for personal ownership, accounting domains and required metrics. | Owner decisions in section 14. | Explicit experimental scope and role/owner/request/attempt/cost semantics; declared durability/limit thresholds; successor architecture marked proposed until required gates pass. |
| **W2 — Reproducible candidate stack** | Pinned LiteLLM → CPA deployment, database, secrets, native account setup and selected Langfuse endpoint. | W1's approved experimental scope; final architecture adoption is not a prerequisite for the isolated POC. | Fresh setup reproducible; recorded digests/schema; two users/four keys; management services private; restart smoke check. |
| **W3 — Client/protocol contract** | Actual IDE/SDK compatibility, stream behavior, model route and retry/cancellation semantics. | W2. | P1 plus safe request correlation manifests and documented unsupported optional routes. |
| **W4 — Personal ownership and limits** | Role isolation, key lifecycle, trusted owner mapping, model restrictions, budgets/rate limits. | W2; W1 policy thresholds. | P2, P3 and P5; negative tests reach no unauthorized upstream request; measured concurrency/outage behavior. |
| **W5 — Metering and retained-data contract** | Selected scoped read APIs, source event identity, raw/normalized fields, cost, completeness, replay and retention. | W2/W3; ownership from W4. | P4, P7 and P8; reconciled synthetic cases, rebuild result and quantified losses; no CPAMP dependency for base totals. |
| **W6 — Personal dashboard gap delivery** | Required panels only; scoped backend and trusted reporting session where a custom UI is necessary. | W4/W5; feature priorities from W1. | P6/P11; normal-user usability, cross-user rejection on every route and visible unknown/stale states. Native-only baseline may need no new UI. |
| **W7 — Native Langfuse integration** | Chosen callback, trusted user/session mapping, metadata-only payload and accepted delivery policy. | W2/W4/W5; policy from W1. | P9/P10; owner attribution, no content leakage, outage isolation and measured restart/duplicate behavior. |
| **W8 — Operations, final adoption and cutover** | Health, backups/restore, retention, upgrades/rollback, capacity and key/history migration; complete the acceptance record before final ADR adoption and cutover. | W3–W7 for selected release scope; W9 only if retained diagnostics are required. | P13 and all other required gates pass; successor ADR/spec explicitly adopted; documented cutover/rollback, preserved historical ownership and a clear list of components ready for retirement. |
| **W9 — Optional CPA diagnostics** | Retained CPAMP deployment, optional correlation and operator account drill-down. | W2; W3 correlation if required. | P12 and proven joins for any enriched rows; exactly one queue consumer; personal reporting works without it. |

Each implementation issue should state what is reused from upstream, what custom
code is necessary, the retained source contract, expected outage behavior and a
small reproducible acceptance case. Avoid a single “build the dashboard” ticket
that hides authentication, persistence and metric-definition work.

## 14. Decisions left for the owner

| Decision | Recommended starting point | Why it remains open |
|---|---|---|
| First release dashboard scope | Native personal Usage/history plus explicitly prioritized missing panels. | “CPAMP-like” is a product description, not yet a fixed metric/UI acceptance list. |
| Identity/onboarding | Native LiteLLM accounts; distinct user-owned keys. | Invitation/password lifecycle and reporting-session integration need runtime acceptance. |
| User/key budgets | Declare policy before implementation; test actual enforcement and allowed overshoot. | Feature availability does not define strictness under concurrency/outages. |
| OSS versus Enterprise | Validate the native-account/scoped-report OSS path first. | SSO, premium report APIs or delegated administration could change the cost/implementation choice. |
| Reporting UI shape | Separate authenticated UI if native panels are insufficient. | Cross-application session establishment and ordinary-user plugin access remain unproved. |
| Additional persistence | Prefer rebuild from native retained events; capture only demonstrated gaps. | Callback-only fields may need a new durable source if they are essential. |
| Langfuse delivery guarantee | Native asynchronous integration with measured/documented semantics. | A durable or lossless requirement may require extra work; no such guarantee was established. |
| CPAMP retention | Optional operator diagnostics. | Depends on whether provider-account quota/health and historical CPA records are needed operationally. |
| Subscription runtime | Keep CPA for the first POC. | Replacing it would add a second compatibility change and needs its own evidence. |
| Existing history and credentials | Preserve original history semantics; reissue keys where migration cannot preserve guarantees. | Group-owned machine history cannot safely become personal history through inference. |

## 15. Reading map and source register

### 15.1 Repository evidence

Read this handoff first, then consult:

- [LiteLLM dashboard assessment](litellm-dashboard-assessment.md): precise
  source-backed feature, plugin, edition and integration findings.
- [New API/Sub2API comparison](new-api-stack-comparison.md): alternative-specific
  evidence; its original Sub2API-first ranking is superseded by this handoff.
- [Original stack research](proxy-stack-research.md): background for the current
  architecture, rather than the proposed personal-usage boundary.
- [Accepted ADR](../adr/0001-architecture-boundaries.md) and
  [glossary](../../GLOSSARY.md): current architecture/terms requiring later revision.
- [Dependency pins](../dependency-pins.md), [live acceptance](../live-acceptance.md),
  [gateway](../gateway.md), [CPAMP adapter](../cpamp-contract.md),
  [projection](../projection.md) and [exporter](../exporter.md): current contracts,
  actual evidence and limitations that must survive a redesign.

### 15.2 Primary external evidence

The references below preserve the research snapshots already inspected on
October 28–29, 2026. Pinned GitHub sources support release-specific conclusions;
documentation links describe the observed docs and may change later. Before
implementation, revalidate the selected version and any gate that determines
product scope. This handoff does not claim a fresh release search beyond those
recorded research observations.

Key source groups:

| Topic | Sources |
|---|---|
| Native users and customer distinction | [Self-service][LL-self-serve], [access control][LL-rbac], [customer usage][LL-customer]. |
| Personal API authorization | [User endpoints][LL-user-api], [scope resolution][LL-scopes], [spend/log routes][LL-spend]. |
| Native charts and retained fields | [Activity component][LL-activity], [request detail][LL-detail], [schema][LL-schema], [logging payload][LL-payload], [log documentation][LL-logs]. |
| Plugins and ordinary-user restrictions | [Plugin docs][LL-plugins], [backend][LL-plugin-source], [central checks][LL-route-checks], [route allowlists][LL-route-types]. |
| Editions | [Edition comparison][LL-editions], [SSO][LL-sso], [JWT gate][LL-jwt], [license][LL-license]. |
| Provider composition | [Responses docs][LL-responses], [pinned adapter][LL-responses-source], [subscription docs][LL-subscriptions]. |
| Langfuse and hooks | [Langfuse integration guide][LF-integration], [SDK callback][LL-langfuse-source], [OTEL callback][LL-langfuse-otel], [identity controls][LL-langfuse-identity], [logging controls][LL-logging], [hooks][LL-hooks], [attempt/request callback distinction][LL-callback]. |
| Alternatives | [New API release][NEW-release], [Sub2API release][SUB-release], and full pinned source register in [the comparison][alternatives]. |

### 15.3 Issue snapshot locations

The read-only issue snapshot used in section 13 corresponds to these existing
issues: [#1][issue-1], [#2][issue-2], [#3][issue-3], [#4][issue-4], [#5][issue-5],
[#6][issue-6], [#7][issue-7], [#8][issue-8], [#9][issue-9], [#10][issue-10].
Issue state and bodies may change after this handoff; the proposed mapping records
their October 29, 2026 scopes.

### 15.4 Completion boundary

This handoff consolidates the research and recommends a testable next architecture.
It does not certify replacement-stack compatibility, isolation, accounting
completeness, plugin access, delivery durability or performance. Those are the
explicit POC outcomes above. The owner can use the spec-delta table, issue map and
work packages to revise the project without losing either the new direction or
the limitations of existing evidence.

[lite-assessment]: litellm-dashboard-assessment.md
[alternatives]: new-api-stack-comparison.md
[live-acceptance]: ../live-acceptance.md
[dependency-pins]: ../dependency-pins.md
[gateway-contract]: ../gateway.md
[projection-contract]: ../projection.md
[cpamp-contract]: ../cpamp-contract.md
[exporter-contract]: ../exporter.md
[issue-guidance]: ../agents/issue-tracker.md
[LL-release]: https://github.com/BerriAI/litellm/releases/tag/v1.106.6
[LL-self-serve]: https://docs.litellm.ai/docs/proxy/self_serve
[LL-rbac]: https://docs.litellm.ai/docs/proxy/access_control
[LL-customer]: https://docs.litellm.ai/docs/proxy/customer_usage
[LL-user-api]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/management_endpoints/internal_user_endpoints.py#L2880-L3018
[LL-scopes]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/management_endpoints/daily_activity_scopes.py
[LL-spend]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/spend_tracking/spend_management_endpoints.py
[LL-activity]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/ui/litellm-dashboard/src/components/activity_metrics.tsx#L250-L387
[LL-detail]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/ui/litellm-dashboard/src/components/logs/detail/LogDetailContent.tsx#L469-L575
[LL-schema]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/schema.prisma
[LL-payload]: https://docs.litellm.ai/docs/proxy/logging_spec
[LL-logs]: https://docs.litellm.ai/docs/proxy/ui_logs
[LL-plugins]: https://docs.litellm.ai/docs/proxy/plugins
[LL-plugin-source]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/plugin_routes.py
[LL-route-checks]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/auth/route_checks.py#L264-L369
[LL-route-types]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/_types.py#L865-L1038
[LL-editions]: https://docs.litellm.ai/docs/enterprise
[LL-sso]: https://docs.litellm.ai/docs/proxy/admin_ui_sso
[LL-jwt]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/proxy/auth/user_api_key_auth.py#L1680-L1720
[LL-license]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/LICENSE
[LL-responses]: https://docs.litellm.ai/docs/response_api
[LL-responses-source]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/llms/openai/responses/transformation.py#L654-L673
[LL-subscriptions]: https://docs.litellm.ai/docs/subscriptions
[LL-hooks]: https://docs.litellm.ai/docs/proxy/call_hooks
[LL-callback]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/integrations/custom_logger.py#L303-L337
[LL-langfuse-source]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/integrations/langfuse/langfuse.py
[LL-langfuse-otel]: https://github.com/BerriAI/litellm/blob/61c6ab78393ef45683dd7d963d2a315bd845e20b/litellm/integrations/langfuse/langfuse_otel.py
[LL-langfuse-identity]: https://docs.litellm.ai/docs/observability/langfuse_integration
[LL-logging]: https://docs.litellm.ai/docs/proxy/logging
[LF-integration]: https://langfuse.com/integrations/gateways/litellm
[CPAMP-analytics]: https://seakee.github.io/CPA-Manager-Plus/docs/en/manual/usage-analytics.html
[NEW-release]: https://github.com/QuantumNous/new-api/releases/tag/v1.0.0-rc.47
[SUB-release]: https://github.com/Wei-Shaw/sub2api/releases/tag/v0.2.18
[issue-1]: https://github.com/obenno/ProxyLens/issues/1
[issue-2]: https://github.com/obenno/ProxyLens/issues/2
[issue-3]: https://github.com/obenno/ProxyLens/issues/3
[issue-4]: https://github.com/obenno/ProxyLens/issues/4
[issue-5]: https://github.com/obenno/ProxyLens/issues/5
[issue-6]: https://github.com/obenno/ProxyLens/issues/6
[issue-7]: https://github.com/obenno/ProxyLens/issues/7
[issue-8]: https://github.com/obenno/ProxyLens/issues/8
[issue-9]: https://github.com/obenno/ProxyLens/issues/9
[issue-10]: https://github.com/obenno/ProxyLens/issues/10
