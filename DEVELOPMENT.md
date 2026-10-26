# Development Notes

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
