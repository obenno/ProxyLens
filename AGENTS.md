# ProxyLens Agent Instructions

## Architecture source of truth

ProxyLens is a Docker Compose stack for exposing authorized AI subscription access as an API, recording usage, supporting user-scoped access, and providing observability.

### Component boundaries

```text
Client / SDK / IDE
        |
        v
ProxyLens integration boundary
  - Keycloak-backed human identity and group references
  - application and client-key mapping
  - request authorization
  - user-scoped usage access
  - Langfuse attribution/export
        |
        v
CLIProxyAPI
  - provider OAuth and credential runtime
  - Codex and other provider API translation
  - model routing and streaming/tool compatibility
        |
        v
Authorized provider subscriptions
```

The usage and observability path is separate from model response forwarding:

```text
CLIProxyAPI usage events
        |
        v
CPA-Manager-Plus Full Mode
  - sole CLIProxyAPI usage-queue consumer
  - authoritative durable request history
  - token/cost analytics
  - operator account and quota management
        |
        v
ProxyLens integration boundary
  - user-scoped usage views
  - Langfuse user/session attribution
```

### Required decisions

- **CLIProxyAPI is the provider/OAuth boundary.** Reuse it for Codex OAuth, provider credentials, model translation, routing, streaming, and tool calls.
- **CPA-Manager-Plus Full Mode is the usage analytics layer.** Use it for persistent request history, token usage, latency, estimated cost, filtering, request inspection, account health, and quota operations.
- **Keycloak owns human identity and group management.** ProxyLens must use Keycloak as the sole authority for users, authentication, groups, memberships, and group administration; ProxyLens owns applications, client keys, policies, request authorization, and derived group-scoped views.
- **ProxyLens owns the resource and authorization boundary.** Keep the custom surface limited to application/client-key mapping, policy enforcement, request correlation, user-scoped usage projections, and integration glue.
- **Langfuse is the observability layer.** Export redacted, user/session-attributed observations. Langfuse is not the authorization source or authoritative billing ledger.
- **Only one service may consume the CLIProxyAPI usage queue for a given CLIProxyAPI instance.** CPA-Manager-Plus Full Mode is the designated consumer. ProxyLens must read a supported CPAMP interface or an explicitly designed export/read integration rather than independently popping the queue.
- **Docker Compose is the reference single-host deployment.** Include Keycloak, ProxyLens, CLIProxyAPI, CPAMP Full Mode, and selected Langfuse services with persistent volumes, private networks, healthchecks, and Compose secrets. Publish only client/API and operator UI ports that are explicitly required.

### Integration rules

- Keep CLIProxyAPI Management API credentials server-side.
- Never expose CPAMP’s manager/admin key to end users.
- Keep Keycloak Admin API credentials server-side; validate user tokens locally against Keycloak’s published keys.
- Issue distinct client credentials per user or application and maintain the mapping outside CLIProxyAPI’s shared operator configuration.
- Preserve streaming, tool calls, multimodal requests, request IDs, and provider/model metadata through the integration boundary.
- Store raw usage fields and normalized exclusive token buckets separately.
- Mark cost as estimated unless an authoritative upstream cost is available.
- Default Langfuse export to metadata, latency, status, model, usage, cost, and correlation IDs; make prompt/output capture explicit and redacted.
- Use stable ProxyLens user identity for Langfuse `userId`; use request/session correlation for `sessionId`.
- Treat the CPAMP/CLIProxyAPI usage record as consumptive input and design for idempotency, queue-loss detection, retention, and replay where supported.
- Treat ProxyLens usage data as a rebuildable projection of CPAMP records; do not independently consume the CLIProxyAPI queue or present the projection as the authoritative usage ledger.
- Do not consider tenant-scoped usage complete until CPAMP read/export and request correlation are verified in a proof of concept.

### Research and design references

- `docs/research/proxy-stack-research.md` — verified capabilities, gaps, architecture, and source register.
- `DEVELOPMENT.md` — implementation decisions, rationale, validation, and follow-up discipline.
- Read relevant ADRs in `docs/adr/` and `GLOSSARY.md` when they are added.

## Agent skills

### Issue tracker

Issues and specs live in GitHub Issues; use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context repository with root `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.
