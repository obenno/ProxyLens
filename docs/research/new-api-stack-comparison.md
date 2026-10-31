# Per-user usage stack comparison: ProxyLens, New API and Sub2API

**Research date:** October 28, 2026.

> **Recommendation update — October 29, 2026:** the subsequent LiteLLM assessment
> changes the first recommendation to **LiteLLM → CLIProxyAPI + Langfuse**. See the
> [consolidated architecture handoff](architecture-handoff-2026-10-29.md). The
> Sub2API-first ranking below is the historical October 28 conclusion; its source
> findings remain evidence for the alternatives comparison.

**Requirement reassessment:** users need subscription-to-API access and a CPAMP-like statistics dashboard **for each user**. Keycloak-owned identity and multi-group synchronization are not requirements for this comparison.

**Evidence level:** primary-source inspection and release verification; neither replacement stack was deployed or tested against providers during this research. Recommendations below are proposals, not changes to the accepted repository architecture.

## Decision summary

**For the clarified requirements, prefer an existing user-aware gateway over continuing the current custom group/CPAMP projection design. Evaluate native Sub2API first; evaluate New API → CLIProxyAPI if retaining CPA's provider runtime matters.** This is a product-fit and likely maintenance-scope judgment, not a measured reliability or performance ranking.

| Candidate | Fit for the requested product | Remaining work |
|---|---|---|
| Current ProxyLens + Keycloak + CPA + CPAMP | Implements group/application policy and CPAMP-derived projections. Machine requests have no human subject; tenant usage remains proof-gated. | Introduce the personal accounting contract, complete correlation/history evidence, and supply the personal dashboard. See `docs/gateway.md:129-139`, `docs/projection.md:163-184`, `docs/live-acceptance.md:42-51`. |
| New API → CLIProxyAPI | Native users, user-owned keys, quota accounting and personal consumption UI; retains CPA as the provider boundary. [user-model] [token-model] [dashboard-api] | Add any missing personal performance/error aggregates, reasoning persistence and asynchronous Langfuse export; verify the extra relay hop. |
| Native Sub2API | Combines subscription OAuth/forwarding with user-owned usage and a comparatively detailed personal dashboard. [sub-oauth] [sub-gateway] [sub-stats] [sub-handler] | Verify actual clients/providers; add separate reasoning-token persistence if required and user-attributed Langfuse export. |
| Native New API for Codex | Direct OAuth-credential Codex channel exists, so CPA is optional for this provider. [codex-adaptor] [codex-oauth] | Same analytics/export gaps; direct-provider equivalence to CPA remains untested. |

The architectural simplification is **assign the requesting user's ownership when accepting their key and persist usage under that ownership**. CPAMP can remain the sole CPA queue consumer for operator diagnostics, but should not be a mandatory join for every personal dashboard row in the proposed design. Client-request accounting and provider-attempt accounting still need distinct definitions.

Proposed request and telemetry flows:

```text
Preferred POC:
Client → Sub2API → authorized provider subscription
             └→ user-attributed usage/errors → asynchronous exporter → Langfuse

CPA-retaining POC:
Client → New API → CLIProxyAPI → authorized provider subscription
             └→ user-attributed logs → asynchronous exporter → Langfuse
                         CLIProxyAPI queue → CPAMP (optional operator diagnostics)
```

Langfuse belongs on the asynchronous observation path. Use the gateway's personal UI/API for users; a Langfuse `userId` filter is an analytics attribute, not a user-isolation policy. [langfuse-users] [langfuse-rbac]

## 1. Verdict

**New API is a credible replacement candidate for the custom per-user gateway, key/quota management, and basic usage dashboard. It is not a verified, complete replacement for CPAMP's provider-side diagnostics or a ready-made Langfuse integration.** Its local users own inference keys, balances and request history; personal dashboard endpoints enforce the authenticated user in the backend. This directly fits the clarified requirement. [user-model] [token-model] [usage-controller] [log-model]

The decisive limits are:

1. **Personal usage dashboards exist.** Request/token/quota/cache totals and model/time views are native. However, the dashboard's performance summary is model/group-wide, not user-specific. Personal latency distributions and failure-rate analytics need additional aggregation. [dashboard-api] [dashboard-cards] [performance-types] [performance-controller]
2. **Separate reasoning-token persistence is missing in the inspected ordinary text log path.** Runtime Responses usage retains reasoning details, but settlement logs persist input/output totals, cache fields and reasoning effort, not the complete raw usage or a separate reasoning-token count. A dashboard/exporter alone cannot recover discarded fields. [responses-usage] [text-quota] [log-info]
3. **Log export is native; Langfuse export is not demonstrated.** Native paginated APIs and NDJSON exports are useful integration surfaces. No first-party Langfuse/OTLP exporter was found in the inspected implementation/configuration. [log-controller] [pat-routes] [source-tree]
4. **The plugin system is a task-provider extension mechanism.** It is not a documented arbitrary dashboard, authentication, or ordinary-relay telemetry hook system. [plugin-contract] [plugin-router]

**For the New API candidate:** use its existing personal UI as the POC baseline. If its basic statistics suffice, it can substantially reduce custom application scope. If “CPAMP-like” includes accurate personal reasoning/cache breakdowns, failure analytics, provider-account/attempt drill-down and Langfuse sessions, plan explicit instrumentation and an exporter/custom view before declaring replacement complete. Section 9 explains why native Sub2API is the first candidate to evaluate against these particular requirements.

## 2. Exact versions and deployability

| Evidence | Verified snapshot |
|---|---|
| Latest published New API release at inspection | `v1.0.0-rc.47`, published `2026-10-25T09:04:29Z`; release commit `e835b1bfc43b565d625537830dbfb19328925134`. GitHub reports `prerelease: false` despite the RC name. [release] [release-api] |
| Inspected `main` | `fcc241cdf8ae0a7ba54107a256b5b0167d5a4fdc`, October 28, 2026, “fix: start affinity fallback at the highest channel priority (#8078)”. [main-commit] |
| Deployable artifacts | Release lists Linux amd64/arm64, macOS and Windows binaries plus checksum files. The multi-architecture Docker publish run succeeded against the release commit. Workflow publishes `calciumion/new-api:v1.0.0-rc.47` for amd64/arm64. Artifacts were not installed or smoke-tested here. [release-api] [docker-run] [docker-workflow] |
| CLIProxyAPI correlation reference | Inspected commit `ad8bdd3f20bef44f0684b8a6096a216b2c76040d`; this is a source reference, not a tested version pair. [cpa-trace] [cpa-usage] |

Source links below target the **release commit**, except explicitly labeled `main` changes. The local release-to-main diff contains 35 changed files; the cited user model, dashboard, logging/export, plugin contract and core Responses relay files are unchanged between those snapshots. The changed Responses DTO is compared separately.

Relevant changes on `main` that must **not** be attributed to RC.47:

- Azure becomes an eligible Responses WebSocket channel. Ordinary OpenAI-type WebSocket channels already qualify in RC.47. [channel-constraints-release] [channel-constraints-main]
- `input_tokens_details.cache_creation_input_tokens` becomes another recognized cache-write representation. RC.47 already supports `cache_write_tokens`; the newly added field is not evidence of released support. [usage-dto-release] [usage-dto-main]
- Stream scanning fixes handling of a raw `[DONE]` line. Do not silently use this fix when assessing the release. [scanner-release] [scanner-main]

**Deployment proposal:** pin the release/image digest for the POC and record it with the tested CLIProxyAPI version. The upstream Compose file supplies New API, PostgreSQL, Redis, persistence and an application healthcheck, but uses a floating application tag. [compose]

## 3. What each user gets

| Requirement | Released implementation | Practical consequence |
|---|---|---|
| Local users and administrator controls | Local numeric user ID, status, role, quota, used quota and request count. [user-model] | No external identity server is necessary for this product requirement. |
| Distinct user/application keys | Tokens belong to `UserId`; creation binds ownership to the authenticated user. Expiry, status, remaining/unlimited quota, model/IP restrictions and routing-group settings are represented. [token-model] [token-controller] | Issue distinct keys for integrations; name them for application drill-down. |
| User and key accounting | Billing reserves and settles wallet/subscription funding and token quota. [billing-session] | Native accounting exists; validate exhaustion, cancellation and concurrency behavior rather than assuming a strict never-overspend guarantee. |
| Personal dashboard | Overview, model analytics and flow sections; separate cross-user section is admin-only. API selection distinguishes personal versus administrator views. [dashboard-sections] [dashboard-api] | Basic per-user UI can be adopted directly. |
| Personal trends and totals | Model/time rollups include request count, total tokens, quota, cache reads and cache creation. [dashboard-cards] [usage-model] | Already covers much of a consumption dashboard; it is not a full latency/error analytics cube. |
| Request inspection | User-filtered log list with token/model/time/type/group/request-ID filters and usage metadata. [log-controller] [log-model] | Supports personal request drill-down and custom charts over retained fields. |
| Per-user latency/failure charts | Logs contain duration and stream outcome; native performance samples have model/group, not user ID. [log-model] [log-info] [performance-types] | Build user-scoped aggregates; do not label the existing performance panel “your latency/success rate.” |
| Provider account health/quota | New API sees the configured upstream channel; CPA's selected credential/attempt requires a verified join. [openai-adaptor] [cpa-trace] [cpa-usage] | A single CPA channel does not automatically expose CPAMP-equivalent account diagnostics. |

### Important accounting and dashboard qualifications

- New API's `Group` is a routing/pricing concept on its user/token models. It is not evidence of Keycloak-style membership synchronization; that distinction is optional identity context here. [user-model] [token-model]
- New API wallet/subscription settlement represents **gateway charges/allowances**, not an authoritative cost of the underlying provider subscription. Keep `gateway_charge` separate from any estimated provider-equivalent API cost. Gateway subscription plans and upstream provider subscriptions are different concepts. [billing-session] [text-quota]
- Dashboard rollups are hourly and buffered in memory, with a default five-minute flush interval. The flush clears the buffer even where persistence errors are unhandled or only logged. Use request logs as exporter input, and treat rollup freshness/completeness as something to verify. [usage-model] [constants]
- Consumption logging defaults on. Error logging is controlled separately: `ERROR_LOG_ENABLED` defaults false in initialization, while the supplied Compose enables it. Not every rejected or retried request is necessarily one durable error row; error-recording policy filters which errors are written. [constants] [initialization] [compose] [relay-errors]
- Inference `sk-` keys and dashboard `nap_` personal access tokens are different credential types. Inference keys remain stored/revealable through the token model/controller; dashboard PATs are hashed and displayed once. Do not assume all credentials share the PAT storage contract. [token-model] [token-controller] [authentication]

## 4. CLIProxyAPI integration and Responses compatibility

### Proposed upstream configuration

Use an ordinary **OpenAI-compatible channel**, an internal CPA base URL such as `http://cliproxyapi:8317`, and a service-owned CPA inference API key. The OpenAI adaptor constructs the endpoint from the channel base URL/request path and sets upstream Bearer authentication. This is a source-supported composition, **not a verified first-party CPA integration**. Keep CPA management credentials outside end-user access. [openai-adaptor]

```text
Clients → New API (user/key authorization, quota, usage UI) → CLIProxyAPI → subscriptions
                 |
                 └→ durable usage logs → proposed asynchronous exporter → Langfuse

CLIProxyAPI usage queue → CPAMP (optional retained operator diagnostics)
```

In this proposed arrangement, basic user attribution comes from New API's authenticated key ownership, without joining CPAMP records. If CPAMP remains, it remains the sole CPA usage-queue consumer. New API logs describe its own gateway requests; they do not automatically replace provider execution/attempt records. This is a proposed change from the current CPAMP-derived projection model, not a migration already performed.

**Additional native capability:** New API also has a direct Codex channel accepting OAuth credential JSON, targeting Codex backend Responses endpoints, plus credential refresh and usage-management code. Therefore it would be incorrect to claim New API always requires CPA for Codex access. This report evaluates the requested CPA-retaining composition; equivalence of direct Codex support to CPA's broader provider runtime was not established. [codex-adaptor] [codex-oauth] [channel-router]

### Protocol boundaries

| Surface | Source-grounded conclusion |
|---|---|
| HTTP Responses | Ordinary POST Responses falls through to the Go relay; non-streaming responses and SSE have dedicated handling and shared usage accounting. [protocol-router] [responses-handler] [responses-usage] |
| Tools and multimodal input | The typed Responses DTO carries raw JSON input, tools, metadata and client metadata; the relay observes tool events and usage. This supports the composition, but does not prove every tool/image/file payload works through CPA. [responses-dto] [responses-usage] |
| Unknown fields / passthrough | Normal handling serializes a typed DTO, so it is not universal unknown-field passthrough. Raw-body mode preserves request bytes and bypasses conversion/parameter overrides; model mapping performed on the DTO does not rewrite that raw body. Prefer identical upstream/client model names for the initial raw-body POC. [responses-request] |
| Native Responses WebSockets | GET `/v1/responses` exists. Each `response.create` runs authentication and request limiting, receives its own request ID, and uses normal billing. One generation is active per connection; the connection pins model/channel/upstream key, supports cancellation, and forwards native upstream events. [relay-router] [ws-controller] [ws-relay] |
| WebSocket limits | Requires an eligible channel with `ResponsesWebSocketEnabled`; this is a protocol-aware session, not an opaque tunnel or automatic HTTP fallback. Test continuation, interruption and key revocation against CPA. [channel-constraints-release] [ws-relay] |
| Other Responses/file endpoints | GET `/v1/responses/:response_id` is wired to task-plugin retrieval, not general upstream response retrieval. Ordinary DTO background support is commented out; several `/v1/files` operations are explicitly unimplemented. A working streaming POST must not be described as complete API coverage. [protocol-router] [responses-dto] [relay-router] |

### Request correlation remains an integration gap

New API generates `X-Oneapi-Request-Id` and its HTTP upstream-ID capture reads that same header name. CPA emits `X-CPA-TRACE-ID`, while its usage reporter generates a separate execution UUID `request_id`. No automatic persisted New API → CPA attempt join was demonstrated. A channel name or shared upstream key is not a per-request join. [request-id] [constants] [upstream-id] [cpa-trace] [cpa-usage]

**Implication:** New API-local user statistics need no CPA join. Adding CPAMP account drill-down or CPA-derived missing usage requires explicit correlation capture and tests, particularly for retries and multiple WebSocket generations.

## 5. Durable logs and export contract

The request log stores user/token/model/channel/group, input/output token totals, quota, integer-second duration, streaming flag, request/upstream IDs and a JSON-encoded `other` field. Metadata includes cache counts, first-response timing and stream outcome. Logs are inserted into `LOG_DB`; insertion failures are logged, not made atomic with billing through a demonstrated outbox. “Durable history” therefore describes successfully persisted rows, not a proven lossless ledger. [log-model] [text-quota] [log-info]

| Endpoint | Scope and use |
|---|---|
| `GET /api/log/self` | Personal request history; backend binds authenticated user ID. |
| `GET /api/log/self/export` | Personal NDJSON export when enabled. |
| `GET /api/log/self/stat` | Personal quota/RPM/TPM statistics, not a complete analytics contract. |
| `GET /api/data/self`, `/api/data/flow/self` | Personal dashboard rollups/flow data. |
| `GET /api/log/`, `/api/log/export` | Administrator history/export across users. |
| `GET /api/data/`, `/api/data/users` | Administrator model/user rollups; username filtering where implemented. |

Routes and scope declarations assign personal usage endpoints to PAT `usage:read`, administrator log/data endpoints to `log:read`, with role authorization still enforced. PATs use Bearer authentication; they are not inference keys. [api-router] [pat-routes] [authentication]

**Practical exporter contract:**

- Lists use `p` and `page_size`, capped at 100. Filters include Unix-second time bounds, type, model/token/group and exact request/upstream IDs; username/channel filters are administrator-only. [pagination] [log-controller]
- Export streams NDJSON rows newest-first and ends with an API success/count or failure object. HTTP 200 alone does not prove a completed export. There is one concurrent export per user; the configurable maximum range defaults to 365 days. This is a query/export-range limit, not a promise of 365-day retention. [log-controller] [log-settings]
- **Personal `id` is a display ordinal**, rewritten for both lists and exports. It is not a stable deduplication key. Ordinary SQL-backed admin rows preserve persisted IDs; ClickHouse admin lists also use display IDs. Validate the chosen database/export combination. [log-model]
- `request_id` is indexed, not unique, and error/consume records must not be assumed to represent distinct client requests. The API exposes no durable external resume cursor or acknowledgement feed. [log-model] [log-controller]

**Recommended exporter design:** use a server-side read-scoped administrator PAT, fixed bounded time windows with overlap, durable deduplication, terminal-result validation, and a persisted checkpoint advanced only after successful processing. Identify records by deployment plus verified persisted row identity where available. A personal-PAT exporter needs a stronger event identity contract; do not silently collapse rows by request ID. Aggregate only the relevant consumption/error types and reconcile retry/stream outcomes before computing success rates.

## 6. Token semantics, missing data and Langfuse

### What is and is not retained

Responses usage accumulation preserves output-token details at runtime and estimates missing output/input usage for interrupted streams. Ordinary text settlement logs retain cache-read/write counts, cache-write lifetime breakdowns, pricing and stream-status metadata; `input_tokens_total` is written only when a normalized source is available. They do not retain the full original usage object or a separate ordinary-text reasoning-token count. `reasoning_effort` is a request setting, not a token measurement. [responses-usage] [text-quota] [log-info]

**Minimum additions for richer analytics:** persist raw upstream usage separately from normalized exclusive buckets, usage provenance/estimated status, explicit reasoning counts when supplied, precise start/end timing, a trusted session identifier, and CPA correlation when required. Missing counts should stay unknown, not be manufactured as zero. These are instrumentation changes, not something a chart or log poller can reconstruct afterward.

### Native integration finding

A tracked-source/configuration search for `langfuse`, `opentelemetry`, `otlp` and standalone `otel` found dependency references, but no implemented first-party Langfuse/OTLP relay exporter or configuration contract in the inspected tree. Indirect OTEL packages in `go.mod` are not evidence of emitted spans. This is a bounded source-inspection finding, not a claim about every external community integration. [source-tree] [go-mod]

**Proposed approach:** a metadata-only asynchronous log exporter can provide user/model/token/cache/quota observations with the field limitations above. Use stable namespaced local user IDs; treat key names as metadata. Real conversation sessions need an explicit persisted session contract. Keep raw prompts, outputs and privileged log diagnostics outside the default export.

Langfuse accepts OTLP over HTTP JSON/protobuf, not gRPC, at its OTEL endpoint; direct v4 ingestion uses `x-langfuse-ingestion-version: 4`. User/session attributes must accompany each span used for filtering. Configure a traces exporter with the documented `/api/public/otel/v1/traces` path where required. [langfuse-otel]

Langfuse usage buckets must be mutually exclusive. For inclusive input/output totals, subtract known cache/reasoning subsets before sending separate buckets; do not send overlapping totals as additional usage. Retain uncertain source values as metadata until normalization is established. Send gateway quota/charge separately from estimated provider-equivalent cost; New API pricing is not proof of the upstream subscription's bill. [langfuse-usage] [text-quota]

## 7. What plugins can actually extend

The released JavaScript **Task Plugin API v1** supports task submission/querying, usage extraction, artifacts, plugin-owned native routes and claims on host image/video/Responses protocols. It has explicit routing, ownership and billing machinery. Ordinary relay requests can bypass plugin execution entirely. [plugin-contract] [protocol-router] [plugin-router]

The inspected contract does **not** document arbitrary dashboard panels, login/group synchronization hooks, or a universal post-request callback for ordinary Go relay traffic. Static route conflicts are rejected. Consequently:

- An external CPAMP-like personal view can consume existing user-scoped APIs.
- An integrated frontend extension requires normal frontend source work unless a separate documented extension contract is established.
- Additional ordinary-request usage persistence or direct Langfuse instrumentation requires a targeted source change or an external capture/export service.

**Do not plan “write a plugin” as the solution to all dashboard and telemetry gaps.** The task-provider hooks do not establish that extension boundary. [plugin-contract] [plugin-router]

Optional OIDC context: built-in OIDC maps identity/profile fields; account creation gives a local common-user role, while existing login returns the local record. Generic OAuth can gate admission using userinfo policy. These paths do not demonstrate ongoing external role/group synchronization. This is not a replacement blocker under the clarified requirement. [oidc] [oauth-controller] [generic-oauth]

## 8. Focused proof-of-concept gates

These are proposed acceptance tests, **not completed validation**:

1. **Personal isolation and usability:** two users, multiple keys each; personal UI/list/export excludes the other user's records. Inspect admin filters separately. Confirm key revocation, quota exhaustion and model restrictions.
2. **Actual client compatibility:** selected IDE/SDK through New API → CPA; Responses non-stream/SSE, tool-call continuation, image input, model aliases, and both normal/raw-body settings. Test required ancillary endpoints rather than assuming coverage.
3. **WebSockets:** multiple sequential generations, cancellation, disconnect, revoked key and continuation on one connection. Verify one settlement per generation and the pinned-channel behavior.
4. **Usage reconciliation:** compare upstream response usage, New API request logs, dashboard rollups and any retained CPAMP records for cache hits, reasoning, interruption, retries and failures. Explicitly quantify fields lost before persistence.
5. **Exporter replay:** prove stable event identity on the selected log database; interrupted exports, overlapping windows and restarts must not silently lose or double-count observations. Verify user attribution and exclusive token buckets in Langfuse.

**Adoption threshold:** native personal totals/history are sufficient only if the user accepts their demonstrated coverage. If precise reasoning, personal performance/error analytics or provider-attempt diagnostics are essential, complete the corresponding data capture and aggregation before removing the existing source of those measurements.

## 9. Sub2API: closest native fit to the clarified requirements

### Version and subscription runtime

Latest published release verified on October 28, 2026: **v0.2.18**, released October 23, 2026, peeled commit `ac1b8f1271be0d674fa6f074403c1410f30a3a81`. Inspected main was `0a2a29b32e6724714c69822296ccd05a6b86bfdd`; the dashboard, ownership handlers, usage model, OAuth implementation, worker pool and quota eligibility files cited here were checked against the release. [sub-release]

Sub2API implements its own OAuth exchange/refresh and direct Codex Responses forwarding. Its Compose deployment comprises Sub2API, PostgreSQL and Redis; a separate CLIProxyAPI service is not required. This establishes the current deployment boundary, not whether historical implementations borrowed code or ideas. [sub-oauth] [sub-gateway] [sub-compose]

### Personal dashboard and usage management

The released user UI provides:

- User request counts and input/output/cache token statistics.
- Standard model-price cost and platform-charged cost.
- RPM/TPM, average response duration, model distribution, hourly/daily trends and quota progress.
- Filtered request history, CSV export, first-token/total duration and optional error views. [sub-stats] [sub-charts] [sub-usage-view]

These are backed by authenticated-user queries: `usage_handler.go` derives the user from the session, validates requested key ownership, checks record ownership, and scopes dashboards/error queries to that user. User error views additionally require `allow_user_view_error_requests`. This is stronger evidence than merely showing a user filter in an administrator UI, but still not a completed independent isolation test. [sub-handler] [sub-routes]

Per-user management also has concrete backend support: API keys resolve to an owning user; authentication checks key limits and user balance or gateway subscription allowances; user/platform quota records contain daily, weekly and monthly USD-denominated limits. The quota semantics depend on mode:

- Standard/balance mode applies user/platform quotas.
- Gateway subscription-plan mode checks that subscription's allowances instead.
- Simple mode bypasses balance/subscription/platform checks; it is not the default choice when those controls are required.
- The inspected user/platform quota checker permits the request when its database lookup fails. Consequently, source presence alone does not establish strict budget enforcement during outages. [sub-auth] [sub-user-quota] [sub-eligibility]

These platform allowances are distinct from the authorized provider subscription being forwarded to. A displayed `actual_cost` is the platform's charge calculation, not the actual subscription invoice. [sub-usage-model] [sub-usage-write]

### Missing data and persistence limits

The usage model stores user/key/provider-account/request/session IDs, requested and upstream model details, cache counts, costs and latency. It records reasoning **effort**, not a separate reasoning-token count. PR **#7912**, proposing reasoning-token persistence/display, was still **open and unmerged on October 28, 2026**. Count that as proposed work, not a released feature. [sub-usage-model] [sub-reasoning-pr]

For explicit reasoning breakdowns, the change must cover upstream parsing, durable schema, API and display. Repainting the dashboard cannot recover discarded data. Existing OpenAI input normalization subtracts cached subsets; output remains inclusive. An exporter must not repeat input normalization or add reasoning on top of already inclusive output. [sub-usage-write]

Usage tasks use a bounded in-process worker pool with synchronous overflow fallback by default. Billing and detail-log insertion remain separate; the best-effort log writer retries synchronously after insertion failure and logs final failure. **Inference:** simpler attribution removes the CPA/CPAMP join, but does not prove lossless history across abrupt crashes or persistent database failure. [sub-workers] [sub-billing]

### Langfuse and extension options

No native Langfuse exporter was found in the inspected upstream release. The documented plugin capability is `openai.oauth.outbound_transport.v1`, with configuration UI support; it does not establish a general personal-dashboard or post-metering hook. Prefer scoped APIs and small upstreamable persistence/export changes over rebuilding user accounting in a transport plugin. [sub-plugins]

A community integration exists at `rxho/sub2api-langfuse`, inspected commit `0404b1a2e1311410c83c5c786313626200d3f1cc` dated September 30, 2026. Its documented upstream decorator captures full prompt/output, uses a bounded volatile queue, and assigns `userId=account:<id>` to the **provider account**, not the requesting platform user. It is an implementation reference, not a ready-made solution to the requested personal attribution. [sub-langfuse-fork]

Proposed export contract:

1. Read persisted user-attributed usage plus appropriately scoped/redacted errors; prefer a stable read interface, with a narrow outbox addition if needed.
2. Set `userId` to the stable namespaced platform-user ID; retain key and provider-account IDs separately.
3. Preserve validated session correlation and request fallback; distinguish client requests from upstream attempts.
4. Export asynchronously, metadata-only by default, with explicit unknown/estimated usage and cost semantics.
5. Verify deduplication, crash recovery and delivery semantics against the chosen Langfuse version. Reuse relevant ProxyLens exporter work after adapting its input and identity contracts. [sub-usage-model] [langfuse-users] [langfuse-usage]

### Recommendation and minimum comparison

**Start with native Sub2API's existing personal dashboard.** It already covers more of the requested personal stats surface than the inspected New API consumption view, while combining the subscription runtime and requesting-user ownership. Prefer New API → CPA when CPA-specific client/provider behavior is an important requirement. Native New API's Codex channel is also worth testing if Codex is the only required upstream; a second gateway is not inherently necessary.

Use the same two users, multiple keys per user, shared authorized provider subscription and actual IDE/SDK for comparison. Exercise nonstreaming/SSE, tools, image input, cache/reasoning usage, failures, retries, cancellation and restart. Compare isolation, user totals, quota behavior and missing/double-counted events. Neither candidate has passed these tests in this research session. No performance superiority or accounting-completeness claim is made.

## Primary-source register

All New API code links use RC.47's exact commit unless labeled `main`. Live documentation was accessed October 28, 2026. Findings distinguish source behavior from unperformed integration tests.

[release]: https://github.com/QuantumNous/new-api/releases/tag/v1.0.0-rc.47
[release-api]: https://api.github.com/repos/QuantumNous/new-api/releases/tags/v1.0.0-rc.47
[main-commit]: https://github.com/QuantumNous/new-api/commit/fcc241cdf8ae0a7ba54107a256b5b0167d5a4fdc
[docker-run]: https://github.com/QuantumNous/new-api/actions/runs/40179150194
[docker-workflow]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/.github/workflows/docker-build.yml
[compose]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/docker-compose.yml
[source-tree]: https://github.com/QuantumNous/new-api/tree/e835b1bfc43b565d625537830dbfb19328925134
[user-model]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/model/user.go#L79-L115
[token-model]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/model/token.go#L14-L35
[token-controller]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/controller/token.go
[billing-session]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/service/billing_session.go
[dashboard-sections]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/web/src/features/dashboard/section-registry.tsx#L26-L77
[dashboard-api]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/web/src/features/dashboard/api.ts#L35-L84
[dashboard-cards]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/web/src/features/dashboard/components/models/log-stat-cards.tsx#L61-L122
[usage-controller]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/controller/usedata.go
[usage-model]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/model/usedata.go
[performance-types]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/pkg/perf_metrics/types.go#L10-L43
[performance-controller]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/controller/perf_metrics.go
[log-model]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/model/log.go
[log-controller]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/controller/log.go
[log-info]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/service/log_info_generate.go
[text-quota]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/service/text_quota.go#L400-L560
[constants]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/common/constants.go
[initialization]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/common/init.go#L205
[relay-errors]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/service/relay_error.go
[authentication]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/docs/authentication.md#L144-L156
[pat-routes]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/middleware/access_token_routes.go#L235-L250
[api-router]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/router/api-router.go
[pagination]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/common/page_info.go#L41-L82
[log-settings]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/setting/operation_setting/log_setting.go
[openai-adaptor]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relay/channel/openai/adaptor.go#L114-L250
[protocol-router]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/router/task-plugin-protocol-router.go
[relay-router]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/router/relay-router.go
[responses-request]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relay/responses_request.go#L24-L86
[responses-dto]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relaykit/dto/openai_request.go#L1056-L1119
[responses-handler]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relay/channel/openai/relay_responses.go
[responses-usage]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/service/responses_usage.go
[ws-controller]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/controller/responses_websocket.go
[ws-relay]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relay/responses_websocket.go
[channel-constraints-release]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/model/channel_constraint.go
[channel-constraints-main]: https://github.com/QuantumNous/new-api/blob/fcc241cdf8ae0a7ba54107a256b5b0167d5a4fdc/model/channel_constraint.go
[usage-dto-release]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relaykit/dto/openai_response.go
[usage-dto-main]: https://github.com/QuantumNous/new-api/blob/fcc241cdf8ae0a7ba54107a256b5b0167d5a4fdc/relaykit/dto/openai_response.go
[scanner-release]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relay/helper/stream_scanner.go
[scanner-main]: https://github.com/QuantumNous/new-api/blob/fcc241cdf8ae0a7ba54107a256b5b0167d5a4fdc/relay/helper/stream_scanner.go
[request-id]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/middleware/request-id.go
[upstream-id]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relay/channel/api_request.go#L507-L509
[cpa-trace]: https://github.com/router-for-me/CLIProxyAPI/blob/ad8bdd3f20bef44f0684b8a6096a216b2c76040d/internal/logging/cpa_trace.go
[cpa-usage]: https://github.com/router-for-me/CLIProxyAPI/blob/ad8bdd3f20bef44f0684b8a6096a216b2c76040d/internal/runtime/executor/helps/usage_helpers.go#L123-L143
[codex-adaptor]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/relay/channel/codex/adaptor.go
[codex-oauth]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/service/codex_oauth.go
[channel-router]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/router/channel-router.go#L86-L89
[plugin-contract]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/docs/plugin-api/v1.md
[plugin-router]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/router/plugin-router.go
[go-mod]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/go.mod
[oidc]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/oauth/oidc.go
[oauth-controller]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/controller/oauth.go#L399-L578
[generic-oauth]: https://github.com/QuantumNous/new-api/blob/e835b1bfc43b565d625537830dbfb19328925134/oauth/generic.go
[langfuse-otel]: https://langfuse.com/integrations/native/opentelemetry
[langfuse-usage]: https://langfuse.com/docs/observability/features/token-and-cost-tracking
[langfuse-users]: https://langfuse.com/docs/observability/features/users
[langfuse-rbac]: https://langfuse.com/docs/administration/rbac
[sub-release]: https://github.com/Wei-Shaw/sub2api/releases/tag/v0.2.18
[sub-oauth]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/service/openai_oauth_service.go
[sub-gateway]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/service/openai_gateway_service.go
[sub-compose]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/deploy/docker-compose.yml
[sub-stats]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/frontend/src/components/user/dashboard/UserDashboardStats.vue
[sub-charts]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/frontend/src/components/user/dashboard/UserDashboardCharts.vue
[sub-usage-view]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/frontend/src/views/user/UsageView.vue
[sub-handler]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/handler/usage_handler.go
[sub-routes]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/server/routes/user.go
[sub-auth]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/server/middleware/api_key_auth.go
[sub-user-quota]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/ent/schema/user_platform_quota.go
[sub-eligibility]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/service/billing_cache_service.go
[sub-usage-model]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/service/usage_log.go
[sub-usage-write]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/service/openai_gateway_usage.go
[sub-reasoning-pr]: https://github.com/Wei-Shaw/sub2api/pull/7912
[sub-workers]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/service/usage_record_worker_pool.go
[sub-billing]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/backend/internal/service/gateway_usage_billing.go
[sub-plugins]: https://github.com/Wei-Shaw/sub2api/blob/ac1b8f1271be0d674fa6f074403c1410f30a3a81/docs/PLUGIN_DEVELOPMENT.md
[sub-langfuse-fork]: https://github.com/rxho/sub2api-langfuse/blob/0404b1a2e1311410c83c5c786313626200d3f1cc/docs/LANGFUSE.md
