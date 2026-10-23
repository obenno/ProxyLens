# Issue tracker

ProxyLens implementation specs live in GitHub Issues. Create issues against the repository's development branch when one exists; keep issue scope small enough to implement and validate independently.

## Required issue structure

Each implementation issue should include:

- **Problem / outcome** — who needs the capability and why.
- **Scope** — what the issue owns.
- **Dependencies** — prerequisite issues, external services, or validation gates.
- **Acceptance criteria** — testable Given/When/Then or checklist criteria.
- **Non-goals** — adjacent work intentionally excluded.
- **Operational notes** — secrets, persistence, health, backup, or rollback behavior where relevant.

## Architecture constraints

- Do not make ProxyLens a second CLIProxyAPI usage-queue consumer.
- Treat Keycloak as authoritative for users, groups, memberships, and group administration.
- Treat CPAMP Full Mode as authoritative for durable CLIProxyAPI request history and usage analytics.
- Keep CLIProxyAPI Management API credentials, CPAMP manager credentials, and provider credentials server-side.
- Tie tenant-scoped usage features to verified request correlation and CPAMP read/export capability.

## Labels and sequencing

Use labels such as `architecture`, `p0`, `p1`, `poc`, `security`, `integration`, and `operations` when available. State blocking dependencies explicitly in the issue body. Link follow-up issues rather than expanding a completed issue beyond its acceptance criteria.
