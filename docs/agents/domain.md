# Domain documentation

ProxyLens is a single domain context. `GLOSSARY.md` distinguishes current-runtime
terms from proposed personal-usage vocabulary. Keep definitions concise and free
of implementation details. Read `docs/specs/litellm-poc.md` and the applicable ADR
before changing ownership, accounting or identity semantics.

## Candidate boundaries

Proposed ADR 0002 assigns native accounts, keys, admission and client-request
accounting to LiteLLM; provider execution to CLIProxyAPI; observability to Langfuse;
optional provider history to CPAMP; deployment and bounded reporting glue to
ProxyLens. Personal ownership is the admitted key owner, distinct from a verified
interactive actor or customer label. These boundaries need POC acceptance before
final adoption. See the shared plan for bounded A1–A6 integration acceptance;
reuse native features and add custom domain/storage contracts only for selected gaps.

For candidate observability, follow the spec's
[native debugging trace contract](../specs/litellm-poc.md#native-debugging-traces)
and [owner decision](../candidate/decisions.md#owner-approved-tracing-objective-october-29-2026).
Transmitted prompts/code, outputs, visible tool interactions and useful errors
belong in the native integration's debugging target, with targeted credential
masking and verified owner/session mapping. Trace attribution (`userId`/session)
is an analysis dimension, not access authorization; #6 records native project
access and content retention. No bespoke UI/access project is selected. Local
tool execution and unsent files are outside gateway visibility. Native coverage
may be missing/truncated; no all-secret-removal guarantee is implied. A minimal
hook requires a demonstrated, selected mapping/credential gap.

## Current implementation boundaries

- **Keycloak** owns human identities, authentication, groups, memberships, and group administration.
- **ProxyLens** owns applications, client keys, policies, request lineage, audit events, derived usage projections, and user-facing authorization.
- **CLIProxyAPI** owns provider OAuth, provider credentials, model translation, routing, streaming, and tool compatibility.
- **CPAMP Full Mode** owns CLIProxyAPI usage-queue consumption, durable request history, usage analytics, account health, and quota operations.
- **Langfuse** owns observability ingestion and analysis, not authorization or authoritative billing.

## Domain-modeling rules

- Current runtime: `Group` is the identity/access boundary; reference stable
  Keycloak IDs, with names/paths only display metadata.
- Candidate: `Platform user` owns `Personal key`; distinguish client request from
  gateway/provider attempt, estimated cost from allowance and subscription spend.
- Preserve original historical ownership. A group ID is not a personal owner;
  credential creator is not proof of an interactive actor.
- Distinguish retained source facts from rebuildable projections and transient
  callback-only measurements; preserve unknown coverage explicitly.
- Record unresolved integration assumptions as validation gates, not as settled contracts.
- Add an ADR only for a hard-to-reverse, surprising decision that resulted from a real trade-off.
