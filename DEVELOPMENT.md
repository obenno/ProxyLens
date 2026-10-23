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
