# Development Notes

## 2026-10-26 — Issue #7 gateway and #5/#9 application wiring

### Scope and decisions

Implemented on `impl/issue-7-gateway`, confirmed clean integration base `9113a97`.
Connected existing signed Keycloak principals, group authority, resource repository,
policy/rate enforcement and lineage instead of introducing parallel identity or
usage models. Application startup now runs checksum-verified migrations before
serving; API installs resource routes with actual `group_ids`/`group-member`
capabilities and scoped audit access. Gateway receives the existing read-only
Keycloak authority secret (`view-users`/`query-groups`) and CPA client credential;
no CPA Management or CPAMP credential is added to that service.

Routing is an explicit operator-attested registry (`deploy/gateway/routes.json`),
empty/deny-all by default. Decision: require both alias and resolved model in the
effective model policy and the attested provider in its provider policy. Reason:
neither alias spelling nor a public model list proves routing. Consequence: every
possible CPA target/failover for an enabled alias must match the registry; operator
changes require synchronized configuration/restart. No model/provider was guessed.
The existing resource authorization transaction now accepts optional requested
model to check both names against the same fresh policy snapshot.

### Behavior and persistence

- Responses only; bounded UTF-8 JSON, duplicate fields/constants rejected, declared
  and chunked body limits, numerical ceilings narrowed by group/application policy.
  Policy timeout starts during upload, not after the body finishes. No model POST
  retries, including pre-byte timeout/connection failure.
- Live matching-issuer flat-group evidence required. Missing groups invoke existing
  durable orphan reconciliation; nested/outage evidence denies without deletion.
  Existing platform-admin reconciliation route is wired; periodic reconciliation
  cadence remains with operations.
- Generated ingress plus migration-007 transport lifecycle commit atomically before
  CPA dispatch. Headers bind actual returned native UUID through existing lineage.
  Fixed row-factory independence in `LineageRepository.bind_response` for the shared
  dictionary-row database adapter; existing positional callers remain supported.
- Successful response/SSE bytes pass through unparsed; tools/multimodal input and
  provider protocol IDs are unchanged. HTTP errors retain 4xx/5xx status with fixed
  redacted body. SSE protocol errors stay bytes, so transport `completed` does not
  claim successful inference. No raw body or arbitrary metadata persistence.
- Disconnect watcher covers header wait and streaming. Total timeout includes
  upstream work/backpressure; idle I/O timeout covers stalled upstream. Cleanup
  closes upstream, then attempts completion metadata for at most three seconds.
  Partial failures terminate the connection without appending a success/event.
- Header-binding DB failure closes upstream before downstream headers. Completion
  DB failure leaves durable pending/unknown intent, emits only generated request ID
  and fixed log event, and degrades readiness. No replay repairs telemetry.
- Exporter contract: `gateway_observations` view, documented in `docs/gateway.md`;
  ownership/observation IDs plus requested/attested routing, policy versions,
  transport outcome/status/timestamps/latency/byte count. Machine subject remains
  null; generated request ID is session. No usage/cost claims or outbox behavior.

### Validation performed

- TDD red/green demonstrated missing management routes, missing gateway, duplicate
  JSON-model bypass, upstream HTTP error handling and slow-upload policy deadline.
- Python 3.12.13, hash-locked dependencies; **229 tests passed, zero skips** against
  dedicated real PostgreSQL `proxylens_gateway` on the coordinator test instance.
  Existing lineage tests additionally isolate schemas. No other agent DB modified.
- Actual loopback socket tests: first SSE byte before upstream release; unmodified
  tool/multimodal payload and service-only credential; signed JWT scope/management;
  revocation across gateway instances; shared key/application rate contention;
  alias/target/provider deny and unverified registry; exact/over-limit and chunked
  bodies; missing/nested/unavailable group; header-wait/midstream disconnect;
  idle/total timeout, HTTP/SSE/transport/unknown errors; native collisions; real
  DB connection/ingress/header/completion failures and no provider replay.
- Ruff check and format pass; Compose configuration passes; CPAMP fenced Python
  example's preexisting formatting failure fixed with no contract changes.
- Test review: public HTTP and durable exporter/lineage seams, external HTTP only
  mocked; real socket barriers rather than buffered ASGI streaming assertions.
  Synthetic fixtures only. No real credential/OAuth material added.

### Files and follow-up boundaries

`gateway.py`, migration `007_gateway.sql`, `resource_identity.py`, `app.py`,
`config.py`, shared `db.py`/`lineage.py`/`resources.py`, Compose and gateway docs.
Projection code is owned by the parallel implementer and was not changed.
Exporter consumes migration-007 interface; operations owns retention/reconciliation
schedule and stale-pending finalization. Live provider, CPA routing/cancellation,
and deterministic CPA→CPAMP correlation remain coordinator acceptance gates;
local synthetic tests do not close them.

## 2026-10-23 — Proxy stack research

### Scope

Researched the proposed ProxyLens stack: CLIProxyAPI for authorized Codex/AI subscription access, CPA-Manager-Plus-style usage analytics, per-user management, Langfuse observability, and Docker Compose deployment.

### Key decision

Treat CLIProxyAPI as the provider/OAuth gateway and build ProxyLens as the group-aware control plane, request-identity gateway, CPAMP read/projection adapter, and Langfuse adapter.

### Implementation consequences

- Use CLIProxyAPI Management API v8 for administration; keep its management credential server-side.
- Keep CPAMP Full Mode as the sole consumer of CLIProxyAPI usage events and read CPAMP durable history through an adapter.
- Map ProxyLens-issued client keys to Keycloak groups/applications for authorization and usage attribution.
- Export redacted, user/session-attributed generation telemetry to Langfuse asynchronously.
- Use Docker Compose with persistent volumes, healthchecks, private networks, and Compose secrets.

### Validation performed

Reviewed official CLIProxyAPI and CPA-Manager-Plus repositories/docs/source, Langfuse self-hosting/token-cost/OTLP docs, and Docker Compose services/secrets docs. Findings are recorded in `docs/research/proxy-stack-research.md`.

## 2026-10-23 — Revised architecture: CPAMP Full Mode plus narrow ProxyLens integration

### Scope

Refined the architecture after comparing custom usage management, LiteLLM, CPA-Manager-Plus Lightweight Panel, and CPA-Manager-Plus Full Mode against the requirements for subscription-to-API access, CPAMP-like usage statistics, user management, Langfuse observability, and Docker Compose deployment.

### Decision

Use CPA-Manager-Plus Full Mode instead of rebuilding the global usage ledger and analytics layer. Keep CLIProxyAPI as the provider/OAuth gateway. Add only a narrow ProxyLens integration boundary for user/API-key identity, authorization, user-scoped usage access, and Langfuse attribution/export.

### Rationale

- CPAMP Lightweight Panel replaces the CLIProxyAPI UI but does not provide persistent monitoring or analytics.
- CPAMP Full Mode already provides SQLite-backed request history, token and latency analytics, estimated cost, filters, request inspection, account health, quota inspection, and usage-derived operations.
- CPAMP is an operator/management panel, not a user-facing multi-tenant API gateway. It does not by itself establish the required user-to-key authorization boundary or private per-user usage views.
- CLIProxyAPI's usage queue is consumptive. CPAMP Full Mode must remain the sole queue consumer for a given CLIProxyAPI instance; competing collectors could split or lose events.
- Langfuse supplies observability and custom dashboards, but it is not the product authorization source or authoritative usage ledger.

### Implementation consequences

- Public model traffic must pass through a ProxyLens-controlled identity/integration boundary before reaching CLIProxyAPI, or use an equivalent existing gateway whose identity can be correlated reliably.
- ProxyLens must not expose CLIProxyAPI Management API credentials or CPAMP manager credentials to end users.
- ProxyLens should read CPAMP's durable history through a supported API/export/read integration. Direct SQLite access is a fallback requiring an explicit compatibility decision.
- ProxyLens must map its authenticated user/application identity to CPAMP request records and Langfuse `userId`, `sessionId`, metadata, and tags.
- Langfuse export must be asynchronous, redacted by default, and resilient to temporary ingestion failures.
- LiteLLM is not a default dependency. Add it only if its gateway features are required and its compatibility with CLIProxyAPI's Responses API, streaming, tool calls, and usage metadata is validated.

### Validation performed

Compared the requirements against the documented CPAMP Lightweight/Full capability split, CLIProxyAPI usage-queue and Management API behavior, Langfuse user/session and token/cost capabilities, and Docker Compose deployment primitives. Detailed evidence and source URLs remain in `docs/research/proxy-stack-research.md`.

### Follow-up work

1. Verify the CPAMP Full Mode read/export surface for request history and filtering.
2. Confirm the exact CLIProxyAPI request identity fields available to CPAMP and the correlation strategy.
3. Build a Compose proof of concept with Keycloak, one CLIProxyAPI provider account, CPAMP Full Mode, ProxyLens, Langfuse, and a redacted usage export path.

## 2026-10-23 — Finalized pre-spec architecture contracts

### Scope

Resolved the architecture and domain decisions required before implementation specs.

### Decisions

- Keycloak is the sole source of truth for human identities, authentication, groups, memberships, and group administration. Phase 1 uses one self-hosted `proxylens` realm with flat groups and no external-Keycloak integration.
- ProxyLens applications and client keys belong to exactly one Keycloak group. Users may belong to multiple groups; access is the union of their permitted group scopes.
- CLIProxyAPI remains the provider/OAuth and protocol boundary. Phase 1 targets Codex OAuth and the required OpenAI Responses-compatible streaming, tools, and multimodal path.
- CPAMP Full Mode is the sole CLIProxyAPI usage-queue consumer and authoritative durable request-history/analytics service. ProxyLens maintains only a rebuildable usage projection.
- ProxyLens uses a supported CPAMP read/export interface first and a version-pinned read-only SQLite fallback only when explicitly enabled. ProxyLens never consumes the CLIProxyAPI queue directly.
- ProxyLens authorization, rate limits, model/provider allowlists, request identity, client-key lifecycle, audit records, usage projections, and asynchronous redacted Langfuse export are in scope. Hard token/cost budgets are deferred until usage freshness and correlation are proven.
- Docker Compose is the single-host reference deployment. High availability, multi-host scaling, multiple CPA/CPAMP connections, nested groups, external Keycloak, and raw prompt/output retention are out of scope for Phase 1.

### Validation gates

The POC must verify CPAMP read/export, request-ID correlation through CPAMP, usage projection freshness within 60 seconds under normal operation, Keycloak OIDC and role mapping, Codex OAuth/streaming/tool forwarding, redacted non-blocking Langfuse export, and restart/dependency-outage behavior.

## 2026-10-24 — Issue #2: Compose and Python service foundation

### Scope and base

Implemented on `impl/issue-2-compose`, based on `integration/phase-1-poc` at
`3fc4aef`. Adds one runnable Compose stack, Python 3.12 FastAPI/httpx/psycopg
entrypoints (`python -m proxylens api|gateway|worker`), configuration tests, and
deployment/maintenance documentation. This is the foundation ticket, not parent
#1's completed identity/provider/usage POC.

### Decisions and rationale

- Digest-pin upstream Python 3.12.15, PostgreSQL 17.11, Keycloak 26.8.1,
  CLIProxyAPI v8.0.40, and CPAMP v1.14.9. Verified official tags, build workflows,
  configuration source, and registry manifests; record evidence in
  `docs/dependency-pins.md`. Python dependency closures are hash-locked separately
  for runtime and development. The local app image is tied to the deployment's
  recorded Git commit and built image ID.
- Separate PostgreSQL service/volume/credential for Keycloak so identity storage
  stays owned by Keycloak; ProxyLens PostgreSQL is its future resource/projection
  store. No local authoritative identity schema is introduced.
- Compose secrets are mounted only to their consumers. Keycloak's wrapper reads
  files and exports values within its process environment, because it lacks a
  generic file-secret option. The realm import uses environment placeholders.
  `secrets/` is ignored, directory mode 0700, files 0644 for nonroot container
  readability through local file-backed mounts. Secret contents never enter
  Compose interpolation or the image build context.
- CPA needs writable configuration (including startup hashing and management
  writes). A networkless initializer atomically seeds a persistent config volume
  from mounted secrets only when absent. Existing config is preserved, including
  upstream rewrites from JSON to YAML. OAuth state has its own persistent volume.
  Rotation is explicit and coordinated, not an implicit overwrite at startup.
- CPAMP Full Mode alone receives the management key at runtime and consumes CPA
  usage via its `http` collector. Runtime logs confirmed v1.14.9 uses CPA's legacy
  `/v0/management/usage-queue` compatibility route. ProxyLens has no usage-queue
  implementation. Its worker receives a CPAMP manager key only for future durable
  history integration; it currently runs only a private health server.
- Publish only loopback gateway 8000, operator API 8001, and Keycloak 8080. CPA,
  CPAMP, databases, worker, and Keycloak management health remain unbound on the
  host. Internal backend/identity/provider networks separate paths; separate
  edge/egress networks provide required ingress and provider/metadata connectivity.
- Use parent #1's existing-local-Langfuse option. Configuration and mounted real
  project-key slots are present; no fake receiver, embedded Langfuse stack, export,
  or delivery claim. Empty endpoint/keys mean unconfigured. Later exporter work
  must validate the real endpoint and its independently backed-up state.

### Important behavior rules

- `/health/live` reports process availability; `/health/ready` performs bounded,
  parallel dependency probes and a real PostgreSQL `SELECT 1`. Failures return
  503 with fixed dependency labels, never exception details/secrets.
- API depends on PostgreSQL and Keycloak discovery; gateway also checks CPA;
  worker checks PostgreSQL and CPAMP. CPAMP/Langfuse are not gateway readiness
  dependencies. Health does not implement request authorization.
- No business routes or forwarding are exposed; they return 404. Later tickets
  own JWT/role/group validation, client keys, database schema, request forwarding,
  CPAMP reads/correlation, usage freshness, and Langfuse jobs.
- Long-form startup dependency conditions wait for health or initializer success.
  Compose does not stop/restart a merely unhealthy dependent after startup.
- CPA's usage queue remains volatile, with 3600-second retention configured.
  CPAMP downtime/CPA restart may lose uncollected data; no recovery guarantee or
  tenant usage completeness is implied. Healthchecks never pop the queue.
- Realm/config/bootstrap secrets initialize persistent state once. Changing files
  alone does not rotate persisted database, Keycloak, CPA, or CPAMP credentials.

### Validation performed

- TDD tracer slices: configuration/management isolation test failed before Compose
  existed; repeatable secret/config bootstrap test failed before scripts existed;
  public health contract tests failed before the application existed. Each passed
  after its implementation. Additional config guards verify pins, state mounts,
  bind-source existence, dependency conditions, and mounted-secret grants; negative
  bootstrap cases verify absent/empty management keys never create an open config.
- All 8 local Python 3.12 tests passed, along with Ruff lint/format checks, Bash
  syntax checks, hash-locked installation, and official standalone Compose v5.6.1
  `config --quiet` validation.
- **Docker Engine is absent.** Supplemental runtime validation used rootless
  Podman and the official Compose CLI through Podman's Docker-compatible socket,
  isolated project `proxylens-issue2-smoke`, loopback ports 28000/28001/28080.
  Built the application Dockerfile; pulled digest-pinned upstream images; initial
  full-stack `up --wait` reached healthy state for every long-running service.
- Verified API/gateway ready=200, real realm discovery and configured issuer,
  worker health command, and empty host port bindings for CPA/CPAMP. CPA logs
  showed CPAMP HTTP queue polling, establishing actual connection bootstrap.
- Rebuilt the final app image and recreated the stack successfully; all services
  returned healthy. CPA initializer explicitly preserved its existing config,
  and Keycloak's persisted realm remained discoverable. Integration-tip merge
  was already up to date at `3fc4aef`.
- Stopped/restarted PostgreSQL, Keycloak, and CPA independently: expected readiness
  failure and recovery occurred. Stopping CPAMP left API/gateway ready and worker
  unavailable; restarting recovered the worker. An immediate post-restart sample
  transiently returned gateway 503; the settled check matched the dependency table.

### Limitations and follow-up discipline

Docker Engine-specific networking, bind-secret behavior, restart semantics, arm64,
fresh-host TLS ingress, and actual backup/restore/upgrade/rollback drills still
require validation. No real provider/OAuth, identity-token acceptance, correlated
usage record, or Langfuse delivery was exercised. CPAMP HTTP health is not proof
of collection freshness or durable-history correlation. Keep those parent #1
acceptance gates open.

Check `compose.yaml`, `Dockerfile`, dependency locks, `deploy/`, `src/proxylens/`,
`tests/`, and both deployment/pin documents together when changing a dependency.
Preserve CPAMP's sole-consumer ownership and explicitly document any new secret
grant, published listener, persistent-state migration, or health contract.

## 2026-10-24 — Issue #3: deterministic request-lineage contract

### Scope and decisions

Based `impl/issue-3-correlation` on integration `d97f7b4`. Added reusable frozen
dataclasses, bounded CPA trace parsing/diagnostic propagation, exact-match
correlation, redacted observation metadata, PostgreSQL repository and migration
`003_lineage.sql`. Interfaces/lifecycle are in `docs/correlation.md`.

Use gateway-generated UUIDv4 ingress IDs and reverse-map only the returned CPA
v8.0.40 full UUIDv7. Incoming IDs, timestamps, shared credentials and provider
Responses object IDs cannot establish ownership. Preserve CPAMP v1.14.9
`(instance, event_hash)` identities one-to-many for retries. Missing/partial,
correlated, duplicate and ambiguous are distinct. Structural correlation does
not certify deployed compatibility.

Retain all competing native-ID claims. A live SQL resolution view removes
ownership from earlier events when a later collision appears, including two
requests from the same owner. Conflicting replay of one CPAMP hash is sticky
ambiguous. Duplicate reads are not second countable attributions. No broader
resource/identity tables, raw content or credentials are stored by this module.

### Validation and integration boundaries

Test-first slices failed before parser, ingress generation, correlation,
PostgreSQL persistence and metadata/gate implementation. Tests exercise production
SQL in unique schemas on the coordinator's disposable PostgreSQL, including
reconnection, concurrent connections, late collisions, rollback, replays and
secrets/unsafe-value rejection. Full suite: **41 passed** (33 new contract/repository
cases, including 9 real PostgreSQL cases); Ruff lint, changed-file format checks
and `git diff --check` passed. No provider or Langfuse delivery is simulated as proof.

#7 must commit resolved ingress ownership before dispatch, bind returned headers
immediately, and own transport/protocol outcomes without replaying provider work
to repair telemetry. #10 must query current resolution for scoped publication,
not trust cached owner columns; it owns projection/cursor transaction wiring.
#8 consumes only allowlisted IDs/status metadata. Migration/startup orchestration,
resource foreign keys and full gateway/projection lifecycle wiring remain those
tickets' responsibilities. Retention must preserve ambiguity/dedup evidence for
the whole projected-history lifetime.

### Blocker / proof gate

`docs/evidence/issue-3-correlation.json` explicitly records no live samples.
Authorized Codex execution → returned CPA header → actual CPAMP collector
persistence remains unproven; no provider OAuth was configured by this workflow.
The pinned-source and synthetic-history evidence lives in
`/data/tmp/opencode/proxylens-phase1/contracts.md`. Tenant usage remains hard-gated
off even if a caller supplies a durable-history proof flag. Enablement requires
an evidence-reviewed change, both #3/#4 gates, and the real scenarios listed in
the artifact. Distinct application credentials are only a possible coarse-owner
fallback, not request-level proof; no irreversible fallback/ADR selected.

## 2026-10-24 — Issue #4: pinned CPAMP durable HTTP adapter

### Scope and decisions

- Based `impl/issue-4-cpamp` on `integration/phase-1-poc` at `d97f7b4`.
- Added async httpx read-only CPAMP v1.14.9 adapter. Analytics POST provides fixed
  filtered windows with both keyset cursor fields; JSONL export stages a retained
  snapshot candidate. Optional status reads diagnose collector faults. Supported
  HTTP exists, so no SQLite fallback or queue implementation is needed.
- `(configured stable CPAMP instance ID, event_hash)` owns deduplication identity.
  Native request IDs can repeat across attempts. HTTP omits internal row IDs,
  execution IDs, original queue JSON/canonical accounting, and exact row cost.
  Preserve omissions rather than deriving IDs from cursors or inventing zero cost.
- Source-specific raw numeric/token metadata allowlists are separate from versioned
  exclusive Codex buckets. Unsupported/missing evidence stays unknown; negative,
  conflicting and inconsistent accounting stays inconsistent. Never add reasoning
  to inclusive output or duplicate raw cached/read counts.
- Bound pages, rows, bodies, JSONL lines and whole-read time. Validate schema,
  ordering, cursor progress, duplicates, conflicting identities and retention
  coverage. Keep last clean analytics result on failure/degradation; expose
  available/stale/degraded/unavailable with fixed redacted reason codes.
- HTTP export has no completeness footer and can end as a valid prefix after a
  server-side failure. It always remains an unverified/degraded rebuild candidate;
  no destructive projection replacement or tenant proof follows from EOF.

### Validation performed

- TDD at public adapter HTTP/result seams: release-derived fixtures, pagination,
  filters, redaction, token uncertainty, malformed/schema/auth/outage cases,
  duplicate/conflict handling, retention and bounded export traversal.
- Final local checks: all 75 repository tests passed (67 CPAMP cases), Ruff lint
  and formatting passed for owned Python files, `git diff --check` passed. Fixtures
  compared equal to captured release response JSON values. Deadline/cancellation
  checks verify stalled streams close; source review corrected contradictory
  `separate_from_input`/`read_included_creation_separate` cache-mode handling.
- `scripts/cpamp-read-poc.py` exercised the actual official Linux amd64 release
  (archive SHA-256 verified), new loopback-only CPAMP data/config, synthetic imports,
  production adapter reads, restart persistence, outage, and real archive/verify/
  delete retention handling. Three equal-timestamp events paginated correctly;
  two share native request ID. Export/raw cache differences normalized to total
  140; auth failed closed, duplicate import skipped all three. Deleted raw history
  became `degraded/retention_gap`; export then returned zero retained rows without
  claiming completeness. Collector stayed stopped; no CPA/provider configured.
- Portable evidence summary: `docs/evidence/cpamp-v1.14.9.json`; full synthetic run
  output: `/data/tmp/opencode/proxylens-phase1/http-proof/adapter-results.json`.
  Evidence host clock is October 23 UTC; session/document date is October 24.

### Contracts and follow-up

`docs/cpamp-contract.md` records source SHA/coordinates, public interface, limits,
freshness/retention/error rules, normalization provenance and reproduction. Own
files: `src/proxylens/cpamp.py`, `tests/test_cpamp.py`, CPAMP fixtures, POC script and
contract/evidence docs. Shared app/config untouched. Projection consumers must
persist identity-based upserts, use overlap/reconciliation, preserve unknowns,
sample collector health and independently enforce tenant proof gates. Live provider
correlation, complete queue delivery and original canonical CPA usage remain
unproven; HTTP access alone does not close parent #1's live acceptance gate.

## 2026-10-24 — Issue #5: Keycloak identity and stable group scope

### Scope and decisions

Implemented on `impl/issue-5-keycloak`, confirmed based on integration
`d97f7b4`. Read issue #5 through `gh --json`, the architecture ADR/glossary,
and independently researched phase-1 contracts/acceptance matrix. This ticket
owns app/config identity wiring, the Keycloak image/realm and dependency locks.

- Separate public browser S256-PKCE, bearer-only API audience/roles, and
  confidential read-only Admin clients. Existing `keycloak_client_secret` file
  is now exclusively the Admin service-account credential. API and resources
  worker receive it; browser/gateway never do. No local identity CRUD or
  membership/cache authority.
- Built-in group mapper emits names/paths, so a small Java protocol mapper
  emits actual stable group UUIDs and signed flatness evidence. Compile against
  JARs from the exact digest-pinned Keycloak 26.8.1 image, with digest-pinned
  JDK compiler; no Maven dependency resolution. Nested children **and parents
  containing children** produce flat=false/empty IDs and are denied. IDs are
  independent of display names. SPI version compatibility is intentional.
- Explicit subject mapper with minimal browser client scopes: the first live
  login exposed that removing default client scopes also removed access-token
  `sub`. Added `oidc-sub-mapper`; final fresh realm import/browser login passed.
- Public interface `identity.py`: immutable verified Principal, Capability,
  GroupAuthority/GroupEvidence, get_principal/get_group_authority dependencies,
  and require_group. Role grants and scope are checked independently. Roles
  from other clients never grant ProxyLens capability. Auditor alone is read-only;
  group-admin applies to every claimed group (documented phase-1 limitation).
- Browser auth validates single-use state/browser binding, code verifier, issuer,
  ID/access signatures/audiences, nonce, subject binding, authorized party and
  optional at_hash. Opaque HttpOnly session stores JWT/CSRF only; every request
  revalidates. Unsafe cookie requests require exact Origin and CSRF. Single API
  process, bounded in-memory sessions; restart requires login. No refresh-token
  persistence; no membership snapshot in sessions.
- PyJWT[crypto] 2.15.1 verified available from PyPI, installed and hash-locked.
  RS256 fixed, typed native UUID subjects/groups, issuer/audience/azp, integer
  exp/iat/optional nbf, typed API roles, 300-second max token lifetime. Strict exp
  boundary; default five-second skew applies to future iat/nbf only.
- Default/max JWKS TTL 300 seconds, serialized refresh at most every 15 seconds,
  including unknown-kid/failure paths. Known cached signing keys plus unexpired
  JWT permit READ while Keycloak is unavailable; no stale-key grace. New login,
  callback and unsafe API requests require reachable group authority. Scope-specific
  USE/MANAGE additionally require live target-group lookup.
- Read-only Admin group existence lookup distinguishes authoritative 404 from
  transport/auth/schema failure. `reconcile(ids, async mark_unusable(evidence))`
  provides resource-worker integration; it never auto-reassigns or repairs IDs.
  **Resource orphan persistence/scheduling/audit remains the resources worker's
  responsibility**, not a new local group table. Missing/nested groups block live
  use/write checks now. Existing orphan flags must also gate resource consumers.
- API readiness includes live group-authority permission check. Bounded local
  token-read availability remains independent from readiness routing.

### Validation performed

- TDD: signed-principal tracer failed before modules existed; malformed-claim
  cases failed before explicit type/subject checks; Admin reconciliation test
  failed before adapter existed; browser tests failed before routes/wiring;
  invalid endpoint configuration tests failed before startup validation.
- 72 Python tests pass: actual RSA verification, wrong issuer/audience/signature,
  expiry/nbf/skew, missing/malformed claims, unsigned/HS256 rejection, bounded
  unknown-kid refresh/rotation/cache deadline, role/scope/multigroup matrix,
  nonce/state/issuer/subject/exchange failures, session replay/CSRF, actual API
  dependency denial before mutation, live-authority outage and orphan-hook results.
  External HTTP is mocked; crypto, FastAPI routing/dependencies and sessions are
  real. No PostgreSQL identity schema exists to replace with mocked persistence.
- Ruff lint/format, Compose v5.6.1 config validation, diff checks, hash-locked
  dependencies and custom-image build passed. A rebuild on this high-core host
  hit Quarkus parallel ZIP file-descriptor exhaustion; bound build-only JVM
  ActiveProcessorCount=2. Rebuild succeeded without changing runtime CPU policy.
  Application Dockerfile build also passed (`400eadae1c77`). Before completion,
  merged integration tip `d97f7b4` (already up to date); clean working tree.
- **Live disposable rootless Podman + Chromium**: dedicated network
  `proxylens-issue5-network`, fresh PostgreSQL 17.6 Alpine container
  `proxylens-issue5-db`, custom Keycloak image `6f7a9afcc7e1`, loopback 28185,
  API 28186; no user/other-agent containers touched. Final image and final realm
  were retested from a fresh disposable database after removing the first test
  instance. Real browser code+PKCE callback and `/api/me` verified actual access
  subject, API audience/role and both group IDs. Admin service account could read
  group records with the seeded read-only roles.
- Live rename preserved IDs; removing membership changed new-token claims;
  deleting/recreating a name kept old ID missing and invoked orphan hook;
  actual nested membership produced rejected signed flat=false token. Created
  a second real RSA signing provider; both published keys validated real browser
  tokens. Stopping Keycloak preserved warm-key token verification, rejected new
  login/Admin calls and rejected verification after injected cache deadline.
  Unknown-kid rotation timing and expiry boundary were exercised in local tests,
  not by a five-minute wall-clock live wait.
- Sanitized live evidence: `/data/tmp/opencode/proxylens-phase1/issue5-live/`
  `browser-result.json`, `behavior-results.json`; harness scripts beside it.
  They contain no bearer/Admin secrets. Disposable setup secret files are separate
  scratch artifacts and are not committed. Session date is 2026-10-24; container
  UTC log timestamps are 2026-10-23 (timezone boundary).

### Limits and future maintenance

Actual application orphan marking, audit transaction and worker schedule must
connect the hook in #9/#6; those are not claimed tested here. No provider calls,
CPAMP correlation, tenant usage or Langfuse behavior is claimed. Docker Engine,
TLS ingress, multiworker sessions, automated existing-realm migration and
per-group role assignments beyond the union model remain outside this check.
Existing issue-2 realms require explicit backed-up client/mapping migration;
import does not overwrite persisted realms. See `docs/identity.md`.

When changing identity, inspect `identity.py`, `keycloak.py`, `oidc.py`, API
lifespan/config, realm/mappers/build and corresponding tests together. Preserve
strict error boundaries, live write checks and no local membership authority.

## 2026-10-24 — Issue #9: durable resources and narrowing policy

### Scope and decisions

Implemented on `impl/issue-9-resources`, based on integration `d97f7b4`. Owns
`db.py`, `resources.py`, `policies.py`, `resource_routes.py`, resource migrations
with prefix 009, tests, and `docs/resources.md`. Identity-owned application,
configuration, packaging and deployment files were not edited.

- PostgreSQL transactions are the durability boundary. Migration startup is
  advisory-lock serialized and checksum verified. Composite application/group
  foreign keys prevent mismatched key ownership; no local users/memberships.
- Keycloak group existence is an async injected authoritative lookup returning
  verified flat-group information. Request claims do not establish existence;
  upstream failure never implies deletion. Identity #5 owns Principal/JWT/role
  validation and group freshness. Resource routes use an injected real dependency
  plus explicit capability/scope adapters rather than implementing JWT again.
- Keys contain 256 random secret bits, with independently generated nonsecret
  prefixes; only SHA256 hashes persist. Issuance reveals plaintext once after
  commit. Rotation revokes the old key with zero overlap and audits atomically.
  Read/authorization connections do not cache revoked/expired key acceptance.
- Explicit model/provider constraints intersect; absent/null is unconstrained at
  that level, empty is deny, no applicable allowlist is deny. Numeric ceilings take
  the minimum. Broader application policies are clipped at use time. Shared
  PostgreSQL rate counters admit application/key budgets atomically in 60-second
  first-request-anchored windows; they are not simultaneous-request semaphores.
- Orphan repair creates a replacement application, revokes old keys, and keeps
  original ownership immutable. Historical request/usage records must never be
  reassigned. Explicit repair/revoke/reconcile events include old/new references.
- Lifecycle mutation/audit failure rolls back together. Authentication denials
  honestly record null identity/scope; scoped audits omit other groups. Database
  outage fails closed with a redacted 503. Gateway must commit its own request
  lineage before dispatch; a committed rate reservation is not automatically
  refunded if subsequent dispatch/lineage fails.

### Validation

TDD red/green slices recorded missing modules/methods and missing rate enforcement,
then exercised production migrations and real transactions against dedicated
PostgreSQL `proxylens_resources` on localhost:55432. Tests cover key persistence,
plaintext absence, policy intersections/updates, expiration, scoped HTTP routes,
orphan reconciliation/repair, outage behavior, audit-constraint rollback, composite
FK mismatch, concurrent rotation and shared rate limits. Independent child Python
processes verify restart durability and committed revocation visibility. Only
external group lookup and verified-principal seams are stubbed.

All 24 repository tests passed (16 resource/route cases plus 8 foundation cases),
including subprocess restart validation. Resource-file Ruff lint/format and
`git diff --check` passed. The real PostgreSQL audit constraint failpoint proved
that a failed rotation preserves the original usable key and writes no partial
replacement/audit. This is local persistence/control-plane evidence, not a live
Keycloak or provider acceptance claim.

### Integration follow-up

`docs/resources.md` freezes gateway methods, fields, errors, policy semantics,
rates, and API routes. Coordinator summary is in the shared phase-1
`resources-contract.md`. At implementation time identity #5 had not merged;
coordinator must run migrations on startup and install the router using #5's
actual Principal dependency, role map and Keycloak group adapter. Joint signed-JWT
API tests and live Keycloak evidence remain integration gates. No app wiring or
live provider/identity proof is claimed by the dependency-injection tests.

## 2026-10-26 — Issue #6 independent operations tranche

### Scope and decisions

Started clean at integration `9113a97` on `impl/issue-6-operations`. Owns
`docs/operations.md`, `scripts/{recovery,ci-tests}.py`, `.github/workflows/ci.yml`,
`operations.py`, `operations_health.py`, migration `006_operations.sql` and tests.
Runtime app/config/Compose wiring is reserved for coordinator continuation after
#7/#10/#8. No neighboring worktrees inspected or edited.

- Separate configurable lifetimes: request/projection/outbox 90 days, audit 365,
  remote observations 90. Strict UTC `< cutoff`; equality retained. Shared writer
  advisory lock and durable monotonic floors prevent expired-source resurrection
  when import/export integrate the helper. Increasing retention cannot recreate
  data already pruned by a prior floor.
- Retention requires explicit gateway/projection/outbox participants; no default
  destructive scheduler. Participant prune, holds, floor update, lineage cleanup
  and deletion audit share one PostgreSQL transaction. Audit failure rolls back all.
- Retained native-ID collision components preserve every conflicting owner: pruning
  one expired owner must never give its surviving peer false attribution. Pending
  work holds have no implicit time expiry; participant retirement must release them.
  Existing lineage event timestamps are first-seen time, so local source-identity
  cleanup is conservative; final CPAMP projection admission uses original event time.
- Typed health consumes existing probes/adapter status, reports independent
  dependency/projection/export states, and discards arbitrary error strings.
  Current CPAMP status cannot prove dropped-event counts/queue coverage; output is
  explicitly unknown. No CPA usage-queue access or automatic upstream deletion.
- Recovery tools require new directories/databases/volumes, preserve current state,
  reject symlink/traversal paths, verify checksums, use 0700/0600 outputs, and never
  print subprocess/server exception details. Credentials enter via private files;
  process arguments never carry their values. Matching recovery-set label, source
  commit/pins/locks and explicit external-store scope accompany each backup.
- Logical PostgreSQL dump and row fingerprints share one exported snapshot; restore
  is transactional into a newly created database with matching-major tools. Cold
  foundation backup uses read-only host source mounts, whole-volume archives, a
  digest-pinned helper and stopped-writer checks. Restore uses new labeled empty
  volumes and never starts services. Secret/config, CPAMP encryption key, and
  external Langfuse stores remain a coordinated operator responsibility.
- OSS Langfuse runbook uses actual v2 observations plus trace DELETE and separate
  blob lifecycle; no Enterprise-only setting advertised as OSS enforcement. Remote
  deletion is not executed by these scripts. Earlier successful foundation restore
  and Langfuse live experiments are acknowledged with their actual limitations.
- CI runs hashed locked install, Ruff lint/format, Compose config and real PostgreSQL
  tests. It creates isolated DBs and fails on any skipped test. No credentialed CI
  service: ephemeral loopback PostgreSQL trust is restricted to the disposable runner.

### Validation performed

TDD red/green at agreed acceptance-matrix seams: absent operations/health/recovery
modules first; then real PostgreSQL exact cutoff, persisted floors/restart,
pending holds, collision ownership, audit rollback and health outage/unknown tests.
Recovery tests reject existing/symlink destinations, public/tampered archives and
archive traversal; populated real PostgreSQL restore checks resources/key
authorization/policies/audit/lineage and every table fingerprint. Only synthetic
group authority is injected; transactions and database utilities are real.

Full independent-base suite passed **201 tests, zero skips** before the additional
source-identity cutoff case. The updated suite is rerun after integration merge.
Ruff lint and Compose config passed; original CPAMP docs fenced-code format failure
is assigned to gateway integration and intentionally not edited here.

Synthetic five-volume cold backup/restore also exercised the actual script through
rootless Podman, digest-pinned PostgreSQL 17.11 helper, fresh volumes only. Fixture
contents and secret copy preserved; existing-volume restore refused; all ten owned
volumes removed. Evidence is private scratch `issue6-cold-f2aa5207/evidence.json`.
This tests archive mechanics, not a new live full-stack restore. Two preliminary
helpers failed safely on local tag lookup/Podman `--mount volume-nocopy` syntax;
digest-only image lookup and portable `-v ...:nocopy` resolved both. No user service
or provider/OAuth credential was touched. Tests' real connection values stay scratch.

### Concrete remaining integration hooks (same issue #6)

1. Central settings/Compose: wire typed retention config and worker cadence; run 006
   with production migrations. Keep cleanup disabled until all participants exist.
2. Gateway #7: terminal request-row prune plus active/uncertain holds; shared lock
   before lineage writes; safe post-dispatch DB-failure/unknown recovery; no replay.
3. Projection #10: original-event-time admission on every incremental/rebuild/replay
   path using `retention_cutoffs`; prune projection children before ingress, preserve
   incomplete coverage/cursors and ambiguity evidence, maintain/release holds.
4. Exporter #8: request-time admission, pending/dead-letter/uncertain holds and
   audited explicit expiry; dedup/immutable-send state must survive all eligible
   replay windows. Shared lock ordering prevents floor/import/export races. Finish
   gateway/projection-to-outbox scanner and worker lifetime wiring.
5. Health: adapt actual #10/#8 snapshots and CPAMP read/status to operator endpoint;
   retain independent readiness/nonblocking exporter semantics, no queue probe.
6. Audit: add redacted integration/export/reconciliation transitions with truthful
   failure behavior. Do not manufacture durable events when PostgreSQL is down.
7. Extend CI database variable provisioning for final gateway/projection/exporter
   suites; rerun all tests non-skipped and frozen-code backup/restore with populated
   final projection/outbox. Exercise final restart/outage/collision/retention races.
8. Remote retention/lifecycle and full final-stack upgrade/rollback remain live
   gates; documented OSS API plan is not proof that remote objects were deleted.

### Integration-tip validation

Committed independent tranche `fcc7476`; merged integration `9aa9d48` (gateway #7
and projection #10) as `bf6700c`, preserving both development-note additions. CI
now provisions their DSN variables too. Gateway's fixture parses PostgreSQL URLs,
so CI emits escaped URLs rather than libpq keyword DSNs; ephemeral trust CI gets a
random nonempty unused password for the mounted-file contract. The first merged
run exposed that URL mismatch and one previously observed resource concurrent-rate
storage error. After correcting the harness, the complete suite passed **258 tests,
zero skipped** in 38.84s. Ruff lint/format (64 files), Compose config and diff checks
passed. Current PostgreSQL recovery test also restores the newly merged schemas,
but only resources/lineage have populated recovery fixtures; final populated
projection/exporter recovery still requires the continuation. No app/config/Compose
runtime edits were authored by this tranche.

## 2026-10-26 — Issue #10: CPAMP-derived usage projection

### Scope and decisions

Implemented on `impl/issue-10-projection`, integration base `9113a97`. Owns
`projection.py`, `projection_settings.py`, `projection_routes.py`, migration
`010_projection.sql`, projection tests and `docs/projection.md`. Coordinator owns
application/configuration/Compose startup wiring.

- Rebuildable PostgreSQL facts derive only from the pinned CPAMP adapter. Distinct
  event hashes survive even when native IDs coincide. Raw HTTP-surfaced tokens,
  versioned exclusive normalization, requested/resolved models, null cost and
  available safe native identifiers stay distinct; no raw content or secrets.
- Fixed overlapping windows (30-second target/5-minute overlap) plus hourly
  retained-history reconciliation discover late imports. All windows stage before
  one atomic records/lineage/checkpoint commit. Advisory locking excludes concurrent
  workers. Failed windows or promotion retain last valid data; restart replays safely.
- Analytics/JSONL EOF cannot prove a complete snapshot. Reconciliation upserts;
  it never infers source deletion. Missing retained records degrade explicitly.
  Unverified export cannot replace anything. Local 90-day retention alone deletes
  expired projection rows, strictly before the UTC millisecond cutoff.
- Every tenant/export join resolves current lineage, invalidating prior attribution
  after late collisions. Group/application state is read live from resource tables;
  orphan repair never reassigns historical ownership. No group guessing.
- Tenant routes require the real identity dependency, READ capability plus scope,
  matching persisted deployment binding and both reviewed live evidence artifacts.
  Evidence digests/pins/instances/scenarios must match. Defaults are disabled;
  synthetic proof is temporary test input only, never a deployment enable flag.
- Missing records, unknown normalization/cost and unknown completeness remain null
  or explicitly observed-only. Health distinguishes unavailable/stale/degraded/
  available; successful polling cannot hide old window ends, unmatched native-bound
  requests or historical retention gaps. Tenant health omits global source counts.

### Validation performed

TDD red/green slices exercised production migrations on disposable real PostgreSQL
17.6 (`proxylens_projection`, localhost:55432), per-test isolated schemas. External
CPAMP/JWKS HTTP only is mocked; real JWT signature checks, repository transactions,
concurrent-worker locking, cancellation, restart/reconnection, trigger-injected
commit rollback, replay/keyset pagination, late imports, source corrections,
rebuild equivalence/failure, stale boundaries, gaps, collision poisoning, scope,
orphan repair and fail-closed proof checks are covered.

Python 3.12.13 with locked requirements: 15 projection/route tests passed; full
repository suite: 203 passed against the dedicated PostgreSQL database. Projection
Ruff lint/format and `git diff --check` pass. No provider/OAuth/live CPAMP correlation evidence
was created or claimed; the production gates remain blocked.

Post-commit integration merge: gateway tip `92b7128` merged as `39b1d43`; full
merged suite **244 passed**. First run had a transient gateway concurrent-rate test
503 versus expected 429 (243 passed); isolated rerun and subsequent full suite
passed. No gateway code was changed for that failure. Projection tests stayed green.

### Integration and follow-up discipline

`docs/projection.md` documents schema, exporter-safe current joins, API helper,
worker lifecycle, migration helper, proof review and exact completeness limits.
API startup must install `install_projection_routes`; worker startup must own
`projection_worker_lifespan`; run migrations before both. #8 must re-resolve lineage
before one finalized generation and respect proof/unknown fields. #6 must coordinate
lineage/exporter retention, outage cleanup and health wrapping. Keep staging private
and collision evidence for at least the entire dependent projected-history lifetime.

## 2026-10-26 — Issue #8: immutable metadata-only Langfuse outbox

### Scope and decisions

Based `impl/issue-8-langfuse` on integration `9113a97`; read issue #8, merged
correlation interfaces and coordinated contract/live reports. Own modules/settings,
PostgreSQL migration `008_exporter.sql`, tests, exporter documentation and synthetic
live proof script. Gateway/shared app/config/Compose are owned by other tickets.

- One finalized root generation per persisted ingress trace/generation ID. Live
  v4.69.0 same-ID enrichment duplicates visible observations; therefore no early
  generation/update or optimistic sink deduplication claim.
- Typed allowlist serializes only trusted ownership/native IDs, verified principal
  subject, safe session, gateway status/time/model/provider, proof-gated exclusive
  usage and explicitly classified cost. Unknown cost stays absent; possible sink
  inference is labeled estimated/not billing. No content-capture or raw-error field.
- Immutable payload bytes at first committed attempt. Before attempt, enrichment
  uses row-lock serialization; later change records a sticky stale flag/hash only.
  Default proof-disabled input finalizes gateway-only `usage_unproven`; future
  proof-enabled incomplete inputs have a bounded explicit partial-finalization wait.
- Durable fenced leases, SKIP LOCKED claims, bounded rows/payload bytes/response/
  attempts/request age/backoff. Admission uses one advisory lock and aggregate spool
  accounting (Phase 1 O(N) tradeoff). Retain terminal dedup rows through local retention;
  reject expired original requests even after pruning. Source scans must remain
  retryable after capacity suppression; aggregate rejection counters are durable.
- HTTP/JSON v4 with bounded credential-file reads and Basic auth. Actual 200 queue-job
  objects accepted; strict partial-success parsing, no response text persisted.
  Established connection failure retries; 429 requires explicit pre-admission trust.
  Timeout/disconnect/5xx/408/malformed success/expired lease are UNCERTAIN, never an
  automatic resend. No credential redirects/environment proxies or provider replay.

### Validation and integration limits

TDD public seams: typed snapshots, real PostgreSQL outbox/leases, external HTTP,
worker drain and actual v2 readback. Red phases preceded serialization, migrations,
repository lifecycle, transport, worker, retention, pre-send fencing and timezone-
stable identity hashing. Independent interpreters verify durable pending claims and
abandoned-attempt recovery. Native cache-write tokens remain a separate exclusive
bucket, not double-counted inclusive input. All tests use synthetic identities.

Live disposable Langfuse v4.69.0 ingestion/readback on 2026-10-26 passed: genuine
loopback connection refusal followed by fresh repository/transport recovery, one
root generation, original IDs, null input/output, empty supplied usage/cost and
`usage_unproven`. Repeated scan/late enrichment scheduled no second send. Machine
user omission reads back as empty string rather than null, verified and recorded
in the proof harness. Evidence: `docs/evidence/exporter-v4.69.0.json`.
Additional actual-sink fault injection accepted a fresh generation then replaced
only its acknowledgement with malformed JSON. The production worker persisted
`UNCERTAIN/malformed_success`, v2 readback showed exactly one generation, and later
drain did not resend it (`docs/evidence/exporter-v4.69.0-uncertain.json`).

Supported Python 3.12.13 environment installed from hash-locked requirements.
Validation before integration merge: 221 tests passed, 9 lineage tests skipped
without their opt-in DSN; all 9 then passed against isolated schemas in the exporter
test database (230 total). Includes 42 exporter cases. Owned-file Ruff lint/format
and `git diff --check` passed. No new runtime dependency or lock change required.
After committing implementation `310d13a`, merged integration `92b7128` via
`a86e862` (gateway #7 and shared wiring). Full supported-Python suite with the
lineage database gate enabled: **271 passed**, zero skips. Owned-file Ruff lint,
format and diff checks passed after merge. Shared app/config/Compose changes are
inherited from integration, not exporter-owned edits.

Concrete gateway/projection scan orchestration, principal-evidence persistence,
health scheduling and retention wiring are deferred to #6 because #7/#10 lifecycle
tables were developing concurrently. Exact methods and mapping are documented in
`docs/exporter.md`; no claim of integrated provider-response isolation yet.
Uncertain read reconciliation, destination-wide auth pause and remote retention
remain operational follow-up. No provider calls/OAuth, live CPAMP attribution or
native usage fabrication occurred. Local deletion is not remote deletion proof.

## 2026-10-26 — Projection/exporter integration and unified validation

### Scope and merge decisions

Verified clean `integration/phase-1-poc` at gateway merge `92b7128`. Merged
`impl/issue-10-projection` tip `f803f07` with `--no-ff` as `9aa9d48`, then merged
`impl/issue-8-langfuse` tip `1b8efb6` with `--no-ff`. The only conflict was appended
`DEVELOPMENT.md` sections; both implementers' additions were preserved verbatim.
Implementation findings are deferred to the coordinator's single correction pass.

### Validation performed

- Supported Python 3.12.13, pytest 9.1.1, real PostgreSQL 17.6 on the existing
  loopback test instance. Each validation batch created its own uniquely named
  database and dropped it afterward. All five test DSN variables were explicitly
  redirected, including `PROXYLENS_TEST_DATABASE_URL` for the nine lineage tests.
- First unified suite: **285 passed, 1 failed, zero skips**. Failure:
  `tests/test_resources.py::test_concurrent_rate_ceilings_share_postgres_across_repository_instances`.
  Concurrent authorization raised `StorageUnavailable` through `db.py:36` instead
  of returning the expected allowed/rate-limited results.
- In a fresh isolated database, that test alone passed; the following full suite
  repeated the same failure: **285 passed, 1 failed, zero skips**. Root cause and
  correction remain open; this is not a clean unified test result.
- Repository-wide Ruff lint passed; format check passed for all 63 Python files.
  Compose v5.6.1 `--env-file /dev/null -f compose.yaml config --quiet` passed.
  Working/staged whitespace checks and verbatim preservation of both development
  sections passed. No runtime credentials or GitHub access were used.
- Test logs/JUnit/validation metadata are under
  `/data/tmp/opencode/proxylens-phase1/merger-20261026-c1eff389099f/` and
  `/data/tmp/opencode/proxylens-phase1/merger-retry-20261026-13f7b392af84/`.

### Remaining #6 wiring

`app.py`/`config.py` must install projection routes and own the CPAMP adapter/poll
lifespan, independent projection/exporter settings, deployment binding and reviewed
proof gate. The worker still needs completion/overlap scans from
`gateway_observations`, current proof-gated `projection_resolved` joins, explicit
transport-outcome mapping, and retained verified-principal evidence or omitted user
attribution. Preserve source eligibility across outbox capacity/storage failures.
Schedule exporter recovery/drain/prune outside forwarding, operator health and
diagnostics, group reconciliation and coordinated lineage/projection/outbox
retention. Wire the required Compose configuration/mounts and validate restart,
outage and response isolation. Existing migrations are discovered at startup;
tenant usage remains disabled pending the reviewed live correlation/history proofs.
