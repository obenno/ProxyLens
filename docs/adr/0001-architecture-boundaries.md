# ProxyLens integration and ownership boundaries

---
status: accepted
date: 2026-10-23
---

**Transition note (2026-10-30):** this remains accepted for the checked-in
existing runtime and historical group-owned data. [ADR 0002](0002-litellm-personal-usage.md)
is now accepted as the target personal-usage architecture after bounded A1–A6
candidate acceptance. It does not supersede this runtime contract until #6
recovery/readiness evidence and separate production cutover approval are complete.
Revised issue scopes and bounded candidate evidence do not authorize an ingress
switch, state migration, key replacement or service retirement.

ProxyLens uses Keycloak as the sole authority for human identity, groups, membership, and group administration; CLIProxyAPI as the provider and OAuth boundary; and CPA-Manager-Plus Full Mode as the sole CLIProxyAPI usage-queue consumer and authoritative usage-history/analytics service. ProxyLens owns the public gateway, application and client-key resources, authorization policies, request correlation, derived group-scoped usage projections, and redacted Langfuse export. ProxyLens must read CPAMP through a supported interface or an explicitly version-pinned read-only fallback and must never independently consume the CLIProxyAPI usage queue. This preserves one queue consumer, avoids duplicated authoritative ledgers, and keeps identity, provider credentials, usage analytics, authorization, and observability under distinct ownership boundaries.

## Consequences

- Keycloak group IDs, not local membership tables, define group scope.
- ProxyLens PostgreSQL stores resource metadata, policies, request lineage, audit events, and rebuildable usage projections.
- CPAMP read/export capability and request correlation are proof-of-concept gates before tenant-scoped usage is considered complete.
- Docker Compose is the reference single-host deployment and includes Keycloak, ProxyLens, CLIProxyAPI, CPAMP Full Mode, and the selected Langfuse services.
