# ProxyLens Proxy Stack Research

**Research date:** 2026-10-23  
**Scope:** CLIProxyAPI as the authorized-subscription gateway; CPA-Manager-Plus-style usage and account visibility; per-user management; Langfuse observability; Docker Compose deployment.

## Executive summary

The recommended design is a **group-aware control plane and telemetry adapter around CLIProxyAPI**, not a replacement provider proxy:

1. **CLIProxyAPI** remains the request gateway and OAuth credential runtime. It exposes OpenAI/Gemini/Claude-compatible interfaces, Codex OAuth, multiple accounts, routing/load balancing, and an authenticated Management API.
2. **Keycloak** owns human identities, authentication, groups, memberships, and group administration.
3. **CPA-Manager-Plus Full Mode** is the sole consumer of CLIProxyAPI's per-request usage queue and the authoritative service for durable request history and usage analytics.
4. **ProxyLens** owns applications, client API keys, authorization policy, request identity, rebuildable group-scoped usage projections, and Langfuse export. It reads CPAMP through a supported interface or an explicitly enabled version-pinned read-only fallback.
5. A **reverse proxy/auth gateway** should be the public entry point. It authenticates machine traffic with ProxyLens-issued client keys, validates human/operator tokens from Keycloak, and forwards authorized model requests to CLIProxyAPI with a service-managed CPA credential.
6. **Docker Compose** should run Keycloak, ProxyLens, CLIProxyAPI, CPAMP Full Mode, PostgreSQL, and the selected Langfuse Web/Worker dependencies with persistent volumes, private networks, healthchecks, and Compose secrets.

The most important product gaps are the CPAMP durable-history read/export contract and reliable request identity correlation. CLIProxyAPI's Management API gives a consumptive queue of request records, but it does not provide a complete multi-tenant identity model. Keycloak must own human/group identity, ProxyLens must own application/key authorization, and tenant-scoped usage must remain blocked until the correlation path is verified.

## Source and evidence policy

Only first-party sources were used: official repositories/docs or official Docker documentation. URLs are listed in the source register. “Verified” statements below describe what the source explicitly documents or implements. “Recommendation” statements are architecture decisions for ProxyLens inferred from those verified capabilities.

## Verified capabilities

### CLIProxyAPI

The official README describes CLIProxyAPI as a proxy server exposing OpenAI, Gemini, Claude, Codex, and Grok-compatible interfaces for CLI-oriented providers. It explicitly lists OpenAI Codex support via OAuth, streaming/non-streaming/WebSocket responses where supported, tools/function calling, multimodal input, multiple accounts with round-robin load balancing, OAuth authentication flows, OpenAI-compatible upstream providers, and a reusable Go SDK. [Verified: CLIProxyAPI README, accessed 2026-10-23.]

The official Management API v8 is rooted at `http://localhost:8317/v8/management`; `/v0/management` remains for existing clients but is near deprecation, and new integrations should use v8. Successful configuration writes persist and hot-reload the service. All management requests, including localhost requests, require a management key; remote access additionally requires `management.allow-remote: true`. [Verified: CLIProxyAPI Management API v8, accessed 2026-10-23.]

Relevant v8 operations include:

- Read/replace/patch/delete configuration nodes.
- List, upload, delete, download, disable, and refresh credential files.
- Start OAuth login for `codex`, `claude`, `antigravity`, `kimi`, `xai`, `devin`, `meta`, and plugin providers; poll/cancel sessions.
- Reset a credential's routing cooldown.
- Read application logs and request error logs.
- Pop per-request usage records from `GET /observability/usage/queue?count=N`.
- Read in-memory API-key success/failure buckets.
- Make authenticated upstream calls using a stored credential.

The v8 usage queue is explicitly a **pop** operation: records are removed from the in-memory queue when returned. The documented record shape includes timestamp, latency, source, `auth_index`, input/output/reasoning/cached/total token counts, failure state, provider, model, alias, endpoint, auth type, API key, and request ID. [Verified: CLIProxyAPI Management API v8, accessed 2026-10-23.]

CLIProxyAPI's configuration docs show the gateway supports normal client API keys, OAuth credential directories, Codex API-key groups, model aliases, excluded models, routing strategies (`round-robin` and `fill-first`), optional session affinity, request retries, file logging, and a usage-statistics toggle. The documented default for `usage-statistics-enabled` is false. [Verified: CLIProxyAPI Basic Configuration, accessed 2026-10-23.]

CLIProxyAPI's official README says built-in usage statistics were removed from CLIProxyAPI and CPAMC starting with v6.10.0, and points users to external services including CPA-Manager-Plus for usage statistics. [Verified: CLIProxyAPI README, accessed 2026-10-23.]

### CPA-Manager-Plus

CPA-Manager-Plus (CPAMP) explicitly states that it is a self-hosted CLIProxyAPI management panel and observability dashboard, not a replacement proxy: it manages and observes traffic through CLIProxyAPI but does not forward model traffic itself. Clients must connect to CLIProxyAPI, not CPAMP. [Verified: CPAMP README and Runtime Model guide, accessed 2026-10-23.]

CPAMP has two modes:

- **Lightweight Panel:** replaces the CPA UI, adds no service/database, and does not provide persistent monitoring or analytics.
- **Full Mode:** a Manager Server on port `18317` with SQLite-backed request history, cost analytics, inspection, backups, and automation.

CPAMP Full Mode consumes CLIProxyAPI usage events, persists request history in SQLite, and provides monitoring, failure diagnosis, usage/cost analytics, account health, quota inspection, and controlled account actions. Its official capability matrix marks SQLite request history, request monitoring, usage/cost analytics, model prices, scheduled account inspection, quota cooldowns, and account action queues as Full Mode capabilities only. [Verified: CPAMP Capability Matrix, accessed 2026-10-23.]

CPAMP monitoring supports filters and views by time, provider, model, project, account, API key, status, failure type, latency, cache state, request type, and trace ID. Caller API keys are masked; historical/deleted keys are not restored. Failure evidence is sanitized and raw failure bodies are not exposed through normal APIs or JSONL exports. [Verified: CPAMP Monitoring guide, accessed 2026-10-23.]

CPAMP usage analytics provides request count, tokens, estimated cost, failure rate, latency, model/API-key/credential rankings, trends, anomaly points, heatmaps, and request drill-down. It estimates cost from collected request events and model prices; provider billing remains authoritative. Missing queue data, expired events, missing token fields, or missing model-price mappings limit accuracy. [Verified: CPAMP Usage Analytics and Capability Matrix, accessed 2026-10-23.]

The CPAMP source shows a collector that can use subscription/RESP, HTTP queue, or RESP polling modes; it authenticates to CLIProxyAPI with the Management Key, normalizes raw usage records, deduplicates inserted events, enriches account snapshots through `auth_index`, and stores events in SQLite. Its manager starts background workers for usage-derived rollups, account history, quota snapshots, automation, and retention. [Verified: CPAMP source files `apps/manager-server/internal/collector/collector.go` and `apps/manager-server/cmd/cpa-manager-plus/main.go`, accessed 2026-10-23.]

### Langfuse

Langfuse self-hosting is officially supported with Docker Compose for local/testing use and with Kubernetes/major cloud deployment options for production. The documented self-hosted architecture includes Langfuse Web, Langfuse Worker, PostgreSQL, Redis/Valkey, ClickHouse, and S3/blob storage. Langfuse Web receives API/UI traffic; the Worker processes events asynchronously. [Verified: Langfuse Self-hosting guide, accessed 2026-10-23.]

Langfuse tracks usage and cost on `generation` and `embedding` observations. Usage and cost may be ingested directly or inferred from model definitions; custom model definitions and prices are supported. Ingested values take priority over inferred values. Langfuse documents input, output, cached, reasoning, and other usage buckets, with the requirement that usage buckets be mutually exclusive. [Verified: Langfuse Token & Cost Tracking, accessed 2026-10-23.]

Langfuse supports per-user and per-session analysis through `userId` and `sessionId`, and recommends propagating these attributes to every span when filtering or aggregating. It supports metadata, tags, environment, release, model parameters, usage details, cost details, and request correlation metadata. [Verified: Langfuse OTEL integration and tracing best practices, accessed 2026-10-23.]

Langfuse accepts OTLP over HTTP/JSON and HTTP/protobuf at `/api/public/otel`; gRPC is not currently supported by the documented endpoint. Direct OTLP ingestion should include `x-langfuse-ingestion-version: 4` for real-time v4 ingestion. Langfuse maps OpenTelemetry GenAI attributes such as model, usage, cost, user ID, session ID, and metadata into its data model. [Verified: Langfuse OTEL integration, accessed 2026-10-23.]

### Docker Compose

Docker Compose defines services as independently runnable container resources described by images/build settings and runtime configuration. Compose supports service dependencies, healthchecks, named volumes, networks, environment files, and secrets. Long-form `depends_on` can wait for a dependency's healthcheck using `condition: service_healthy`. [Verified: Docker Compose Services reference, accessed 2026-10-23.]

Docker documents Compose secrets as files mounted at `/run/secrets/<secret_name>` and granted only to services that explicitly list them. The docs specifically recommend secrets for passwords, certificates, and API keys instead of environment variables. [Verified: Docker Compose Secrets guide, accessed 2026-10-23.]

## Requirements-to-capability mapping

| ProxyLens requirement | Existing verified support | Gap / implication |
|---|---|---|
| Turn authorized Codex/AI subscriptions into an API | CLIProxyAPI provides Codex OAuth, other OAuth flows, compatible API endpoints, credential files, and routing/load balancing. | ProxyLens must wrap rather than reimplement provider OAuth and upstream translation. |
| Token-usage stats similar to CPAMP | CLIProxyAPI emits per-request queue records; CPAMP demonstrates normalization, SQLite persistence, rollups, pricing, and dashboards. | CPAMP must remain the sole queue consumer. ProxyLens needs a supported CPAMP read/export adapter and a rebuildable derived projection, not a competing ledger. |
| Per-user management | CLIProxyAPI manages global config, provider credentials, and shared client API keys. Keycloak provides human/group identity and roles. | ProxyLens owns applications, client-key lifecycle, policy, request authorization, and group-scoped resources without duplicating Keycloak membership. |
| Per-user usage visibility | Queue records include caller API key and request metadata; Langfuse supports user/session dimensions. | ProxyLens must validate a reliable request-ID/identity correlation path into CPAMP before exposing group-scoped usage. Do not rely on raw upstream account identity as the end-user identity. |
| Langfuse observability | Langfuse accepts OTLP and tracks generations, tokens, costs, users, sessions, metadata, and tags. | CLIProxyAPI does not document native Langfuse export. ProxyLens needs an adapter/OTel exporter and a redaction policy. |
| Docker Compose deployment | Docker Compose supports the required services, dependencies, volumes, networks, healthchecks, and secrets; Langfuse documents Compose deployment. | Compose is suitable for a single-host deployment, but backups, upgrades, resource sizing, and production HA remain operational responsibilities. |

## Integration gaps and risks

### 1. Destructive usage queue semantics and ownership

The CLIProxyAPI usage endpoint removes records from the queue when read. A collector crash after pop can lose events unless the collector has its own durable handoff or uses a transport supported by the running CLIProxyAPI version. CPAMP's collector demonstrates practical queue consumption but its own docs acknowledge that requests missed after queue expiry or while the Manager Server is offline cannot be recovered.

**Decision:** CPAMP Full Mode is the sole CLIProxyAPI usage-queue consumer. ProxyLens must not pop the queue, compete with CPAMP, or claim independent recovery of queue records. The POC must verify CPAMP's supported durable-history read/export surface, freshness, filtering, and loss reporting. ProxyLens may retain only a rebuildable projection of records read from CPAMP.

### 2. No native tenant/RBAC boundary

CLIProxyAPI's Management API is a privileged control API and the normal CPA API keys are gateway credentials. The official docs do not describe per-user roles, team isolation, per-key quotas, or a tenant-safe management delegation model.

**Decision:** expose only ProxyLens endpoints publicly. Keep CLIProxyAPI Management API credentials and CPAMP manager credentials server-side. Keycloak is the sole authority for human users/groups/memberships. ProxyLens issues client keys per application, stores only hashes, maps each application/key to exactly one Keycloak group, and records the authenticated principal before sending a service-owned CPA credential upstream.

### 3. Caller identity and Langfuse attribution

The CPA usage record can contain `api_key`, `source`, and `request_id`, but the exact caller metadata available may vary by protocol/provider and the source field is not a documented tenant identity contract. Langfuse can filter by user ID/session ID only when ProxyLens supplies those attributes consistently.

**Decision:** Keycloak is the human identity authority and ProxyLens is the request-authorization authority. At ingress, resolve a client key to `application_id` and `keycloak_group_id`; for human/admin traffic validate the Keycloak subject, roles, and group claims. Generate a ProxyLens request ID, propagate it through a supported path, and verify the join to CLIProxyAPI and CPAMP records before enabling tenant-scoped usage. Use CPA's API-key field for correlation only when validated, never as the sole authorization source.

### 4. Token and cost semantics differ from provider billing

CLIProxyAPI records token fields when available. CPAMP estimates cost from model prices, and Langfuse can infer cost from model definitions. Both are analytics estimates unless exact upstream cost is ingested. Reasoning/cached token fields require careful exclusive-bucket normalization.

**Recommendation:** store raw CPA token fields and a normalized exclusive usage object separately. Mark cost as `estimated` unless an authoritative cost field exists. Maintain a versioned pricing table and allow per-model/provider overrides. Send explicit Langfuse `usage_details` and `cost_details` when ProxyLens has a trusted value; otherwise configure Langfuse custom model definitions for inference.

### 5. Sensitive data exposure

CLIProxyAPI manages OAuth credential files and exposes privileged authenticated upstream calls. CPAMP explicitly redacts caller keys and failure evidence. Langfuse can store inputs, outputs, metadata, and traces, which creates a separate data-retention surface.

**Decision:** never send OAuth tokens, management keys, client-key secrets, raw authorization headers, or full raw prompts/responses to Langfuse by default. Phase 1 disables raw prompt/response retention. Any future content capture requires an explicit tenant/application specification with redaction and retention rules.

### 6. Provider/model alias drift

CLIProxyAPI supports aliases and provider-specific model names. CPAMP warns that cost is empty or underestimated when aliases are missing from model prices. Langfuse matches prices by model pattern and applies model-definition changes only to new generations.

**Recommendation:** persist both requested model and resolved/provider model. Export the resolved model plus alias metadata. Maintain one versioned model identity/pricing registry in ProxyLens and synchronize explicit custom definitions to Langfuse.

### 7. Deployment scope

Langfuse's own docs describe Docker Compose as suited to local use/testing without high availability, scaling, or backups. Compose can run the whole stack on one host, but it does not itself provide a production database backup/restore or HA strategy.

**Decision:** define Compose as the reference single-node deployment. Include Keycloak, ProxyLens, CLIProxyAPI, CPAMP Full Mode, and selected Langfuse dependencies. Add healthchecks, resource limits, persistent volumes, secret files, backup commands, and documented upgrade order. High availability, multi-host scaling, multiple CPA/CPAMP connections, and externally managed Keycloak are out of Phase 1.

## Recommended architecture

```text
Clients / IDEs / SDKs
          |
          v
  Reverse proxy / TLS
          |
          v
  ProxyLens Gateway  -----> ProxyLens DB (resource metadata, policy,
           |                  request lineage, audit, usage projection)
           |                         |
           |                         +--> Langfuse OTLP exporter / spool
           v
  CLIProxyAPI :8317
    |       |
    |       +--> OAuth credential store (Codex/Claude/Gemini/etc.)
    |
     +--> Usage queue / RESP subscription
                   |
                   v
           CPA-Manager-Plus Full Mode
             - sole queue consumer
             - authoritative durable request history
             - usage analytics and account operations
                   |
                   v
           ProxyLens CPAMP read/projection adapter
                   |
                   +--> rebuildable group-scoped usage projection
                   +--> Langfuse generations with Keycloak subject/group metadata
```

Keycloak runs alongside ProxyLens as the sole human identity and group authority. CPAMP's manager/API surface remains private to the operator network.

### Components

#### ProxyLens Gateway

- Authenticate user/application client keys.
- Resolve `client_key -> application/group/policy` and validate human/operator tokens through Keycloak.
- Enforce model/provider allowlists, request-size and timeout limits, and request-rate limits before forwarding. Hard token/cost budgets are deferred until usage freshness and correlation are proven.
- Forward compatible API traffic to CLIProxyAPI using a service-managed CPA API key.
- Attach a correlation/request ID and preserve protocol behavior, streaming, tools, and multimodal payloads.
- Avoid placing the CLIProxyAPI Management API on the public client path.

#### ProxyLens Control Plane

Suggested domain objects:

- `applications` owned by exactly one Keycloak group.
- `client_keys` with hash, prefix, status, application/group reference, created/rotated/revoked timestamps, and optional expiry.
- `policies` for model/provider allowlists, request limits, and rate limits.
- `cpa_connections` containing encrypted CPA URL and management credential reference.
- `provider_accounts` as redacted metadata references to CPA credential/auth indices; OAuth secrets stay in CLIProxyAPI.
- `request_lineage` for ProxyLens identity, CPA request ID, CPAMP record ID, status, timestamps, and correlation state.
- `usage_projection` for rebuildable CPAMP-derived normalized request facts and group/application views.
- `audit_events` for authorization, key, policy, integration, reconciliation, export, and deletion actions.
- `pricing_versions` and model alias/resolution metadata used to display analytics without becoming billing authority.

#### CLIProxyAPI Adapter

Use v8 Management API endpoints for configuration and OAuth administration. CPAMP Full Mode, not ProxyLens, consumes the usage subscription/RESP or HTTP queue. The ProxyLens adapter should:

- read durable request history through a supported CPAMP API/export/read interface;
- use a version-pinned, read-only SQLite fallback only when explicitly enabled;
- preserve CPAMP record IDs, raw fields, normalized token buckets, correlation IDs, timestamps, model, provider, and status;
- report available, stale, degraded, and unavailable adapter states;
- rebuild or incrementally refresh only the derived ProxyLens usage projection;
- periodically refresh credential metadata through `/credentials`;
- expose controlled admin actions such as OAuth start, credential disable, cooldown reset, and config updates only to authorized ProxyLens administrators.

#### Usage and analytics store

Start with PostgreSQL for ProxyLens resource metadata, policies, request lineage, audit events, and rebuildable usage projections. CPAMP remains authoritative for durable request history and analytics. If projection volume grows materially, retain PostgreSQL for control-plane state and move derived analytical views to a dedicated OLAP store; Langfuse already uses ClickHouse in its self-hosted architecture.

#### Langfuse exporter

Create one Langfuse generation per model request, with:

- `userId`: validated Keycloak subject when a human identity is available;
- `sessionId`: client-provided session ID when allowed, otherwise a generated request/session correlation;
- `model`: resolved model name;
- `usage_details`: mutually exclusive input/output/cache/reasoning buckets;
- `cost_details`: only when trusted or explicitly estimated;
- metadata: Keycloak group ID, application, CPAMP record ID, CPA provider, auth index (prefer a stable redacted account ID), CPA request ID, endpoint, status, latency, correlation state, and pricing version;
- tags: environment, protocol, provider, success/failure class.

Use an asynchronous exporter with retry/backoff and a local spool. Langfuse should improve observability, not become the authorization or billing source of truth.

#### Docker Compose stack

Recommended services:

- `proxylens-gateway` — public API/proxy path;
- `proxylens-api` — control-plane API and admin UI backend;
- `proxylens-worker` — CPAMP read projection, reconciliation, and Langfuse export;
- `cliproxyapi` — OAuth/provider gateway;
- `cpamp-full` — sole CLIProxyAPI usage consumer, durable request history, and operator analytics;
- `keycloak` — human identity and group authority;
- `postgres` — ProxyLens control plane and event store;
- `langfuse-web`, `langfuse-worker`;
- `langfuse-postgres`, `langfuse-redis`/`valkey`, `langfuse-clickhouse`, and S3-compatible blob storage, following the selected Langfuse Compose distribution;
- optional `otel-collector` if ProxyLens emits standard OTLP and needs buffering/routing.

Use named volumes for CPA auth/config, ProxyLens database/backups, and Langfuse dependencies. Use Compose secrets for management keys, database passwords, Langfuse credentials, and encryption keys. Add healthchecks and long-form `depends_on` for database/cache readiness. Keep internal services on private networks; publish only the gateway/admin ports needed by operators.

## Suggested implementation phases

### Phase 1: single-instance proof of concept

- Compose Keycloak, CLIProxyAPI, CPAMP Full Mode, ProxyLens API/gateway/worker, PostgreSQL, and redacted Langfuse export.
- Use one Keycloak realm, one flat group, one application, and one ProxyLens client key.
- Configure Codex OAuth through the CLIProxyAPI Management API.
- Proxy the required OpenAI Responses-compatible streaming, tools, and multimodal requests through CLIProxyAPI.
- Verify CPAMP durable-history read/export and request-ID correlation.
- Show a basic group-scoped usage projection only after correlation is proven.

### Phase 2: multi-group control plane

- Add Keycloak multi-group access, roles, client-key rotation/revocation, policy checks, rate limits, and group/application aggregates.
- Add request-lineage reconciliation, orphan detection, strict secret redaction, and freshness states.
- Add provider/account admin views backed by CLIProxyAPI `credentials` and quota/health operations.

### Phase 3: operational maturity

- Add async OTLP export with user/session/team metadata.
- Add custom model definitions/pricing synchronization.
- Add retention, backups, CPAMP queue-loss monitoring, dead-letter handling, projection rebuild, and replay from CPAMP where supported.
- Add healthchecks, audit logs, metrics, alerts, and upgrade/rollback documentation.

## Decisions to preserve

1. **CLIProxyAPI is the provider gateway and OAuth boundary.** Do not duplicate provider token exchange in ProxyLens unless a documented product requirement makes that unavoidable.
2. **Keycloak is the human identity and group authority.** ProxyLens references stable Keycloak IDs and does not duplicate authoritative membership.
3. **CPAMP Full Mode is the authoritative CLIProxyAPI usage-history and analytics service.** ProxyLens maintains only a rebuildable derived projection.
4. **ProxyLens must never independently consume the CLIProxyAPI usage queue.** Tenant usage requires a validated CPAMP read/export and request-correlation contract.
5. **Raw prompts/responses are disabled by default.** Default observability carries metadata, model, token counts, cost classification, latency, status, and correlation IDs without secrets or sensitive content.

## Finalized architecture contracts and validation gates

The following decisions are settled for Phase 1:

- One self-hosted Keycloak `proxylens` realm; Keycloak is the sole identity/group authority. Groups are flat, users may belong to multiple groups, and applications/client keys belong to exactly one group.
- One CLIProxyAPI instance paired with one CPAMP Full Mode instance. Multiple connections, failover, high availability, multi-host scaling, and externally managed Keycloak are out of scope.
- ProxyLens enforces authentication, authorization, model/provider allowlists, request-size and timeout limits, and rate limits. Hard token/cost budgets wait for validated usage freshness and correlation.
- Usage projection freshness target is within 60 seconds under normal operation. Stale, degraded, and unavailable states must be visible; missing data must not be represented as zero.
- Langfuse export is redacted, asynchronous, and non-blocking. The default payload excludes prompts, outputs, credentials, authorization headers, and raw failure bodies.

The POC must verify:

1. CPAMP's supported durable-history read/export surface, with read-only SQLite fallback explicitly version-pinned if needed.
2. ProxyLens request ID correlation through CLIProxyAPI into CPAMP records, including native IDs and failure states.
3. Keycloak OIDC login, local JWT validation, group claims, and client-role mapping.
4. Codex OAuth plus Responses-compatible streaming, tools, multimodal requests, disconnect handling, and retry behavior.
5. Redacted Langfuse export, retry/spool behavior, and non-blocking provider responses.
6. Restart, CPAMP outage, Keycloak outage, ProxyLens database failure, stale projection, and orphaned-group behavior.

## Source register

All sources accessed on **2026-10-23** unless a source page states otherwise.

### CLIProxyAPI

- Repository README: https://github.com/router-for-me/CLIProxyAPI/blob/main/README.md
- Management API v8: https://help.router-for.me/management/apiv8
- Legacy Management API and usage queue details: https://help.router-for.me/management/api
- Basic configuration: https://help.router-for.me/configuration/basic.html
- Docker Compose guide: https://help.router-for.me/docker/docker-compose.html

### CPA-Manager-Plus

- Repository README: https://github.com/seakee/CPA-Manager-Plus/blob/main/README.md
- Runtime model: https://seakee.github.io/CPA-Manager-Plus/docs/en/guide/runtime-model.html
- Capability matrix: https://seakee.github.io/CPA-Manager-Plus/docs/en/reference/capability-matrix.html
- Monitoring: https://seakee.github.io/CPA-Manager-Plus/docs/en/manual/monitoring.html
- Usage analytics: https://seakee.github.io/CPA-Manager-Plus/docs/en/manual/usage-analytics.html
- Client configuration: https://seakee.github.io/CPA-Manager-Plus/docs/en/gateway/clients.html
- Collector implementation: https://github.com/seakee/CPA-Manager-Plus/blob/main/apps/manager-server/internal/collector/collector.go
- Server/worker wiring: https://github.com/seakee/CPA-Manager-Plus/blob/main/apps/manager-server/cmd/cpa-manager-plus/main.go

### Langfuse

- Self-hosting architecture: https://langfuse.com/self-hosting.md
- Token and cost tracking: https://langfuse.com/docs/observability/features/token-and-cost-tracking.md
- OpenTelemetry integration: https://langfuse.com/integrations/native/opentelemetry.md
- Trace best practices: https://langfuse.com/docs/observability/best-practices.md
- Official model definitions source: https://github.com/langfuse/langfuse/blob/main/worker/src/constants/default-model-prices.json

### Docker

- Compose services reference: https://docs.docker.com/reference/compose-file/services/
- Compose secrets: https://docs.docker.com/compose/how-tos/use-secrets/
- Environment variable precedence: https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/
