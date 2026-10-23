# Domain documentation

ProxyLens is a single domain context. `GLOSSARY.md` is the canonical vocabulary for identity, group ownership, model access, usage, correlation, and observability terms. Keep definitions concise and free of implementation details.

## Source-of-truth boundaries

- **Keycloak** owns human identities, authentication, groups, memberships, and group administration.
- **ProxyLens** owns applications, client keys, policies, request lineage, audit events, derived usage projections, and user-facing authorization.
- **CLIProxyAPI** owns provider OAuth, provider credentials, model translation, routing, streaming, and tool compatibility.
- **CPAMP Full Mode** owns CLIProxyAPI usage-queue consumption, durable request history, usage analytics, account health, and quota operations.
- **Langfuse** owns observability ingestion and analysis, not authorization or authoritative billing.

## Domain-modeling rules

- Use `Group` for the identity and access boundary; do not introduce a parallel authoritative `Team` or membership model.
- Reference Keycloak users and groups by stable IDs. Names and paths are display metadata.
- Distinguish authoritative usage records from rebuildable ProxyLens usage projections.
- Record unresolved integration assumptions as validation gates, not as settled contracts.
- Add an ADR only for a hard-to-reverse, surprising decision that resulted from a real trade-off.
