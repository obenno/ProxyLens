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
