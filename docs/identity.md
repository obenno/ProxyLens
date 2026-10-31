# Keycloak identity and group authorization

> **Current implementation / original #5.** Native-account configuration folds
> into #2 with shared checks in #7 under the [plan](specs/litellm-poc.md). This Keycloak
> contract remains applicable to existing services until approved cutover.

## Realm and clients

One self-hosted `proxylens` realm owns all human identities and memberships.
The first-boot import defines:

| Client | Contract |
| --- | --- |
| `proxylens-browser` | Public authorization-code client, S256 PKCE required; exact redirect URI; no password, implicit, or service-account grant |
| `proxylens-api` | Bearer-only audience; roles `platform-admin`, `group-admin`, `group-member`, `auditor` |
| `proxylens-admin` | Confidential service account; no browser/password flow; `realm-management` view-users/query-groups only |

The Admin secret is `secrets/keycloak_client_secret`, mounted only to Keycloak,
API and worker. Its historical file name is retained; it is **not a browser
secret**. Keycloak is the only place to create/edit users, memberships, groups
and role assignments. Assign roles from `proxylens-api`, not similarly named
realm roles or another client. Do not enable fine-grained visibility filtering
for this service account: authoritative existence checks require full group view.
No local user/group CRUD or membership database exists.

Build with `docker compose build keycloak`. The image compiles the small
`deploy/keycloak/mapper` provider against **the exact Keycloak 26.8.1 image's JARs**,
then runs `kc.sh build`. No Maven resolution, JavaScript preview feature or
user-editable attribute substitutes for membership. The mapper emits:

- `proxylens_group_ids`: sorted, distinct native group UUID strings;
- `proxylens_groups_flat`: boolean; false with an empty ID array for nested
  membership, membership in a group containing children, or over 256 groups.

The API rejects false/missing flat evidence. Names, paths and renames never grant
scope. The explicit subject mapper is necessary with the browser's empty default
client scopes; the access JWT must carry native `sub`. All audience, role and
group mapping is server-managed. Native UUID subjects are supported; external
federated identities are outside this phase's realm contract.

### Existing foundation realms

Realm import is initialization-only. A realm created by issue #2 will not gain
these clients on restart. Back up Keycloak first; use the Admin console to apply
the clients/mappers/role scope mappings/service-account grants in
`deploy/keycloak/proxylens-realm.json`, with the mounted secret and exact redirect.
Disable the old `proxylens` confidential browser client after migrating. Never
delete an existing realm to force an import. Rebuild the image before adding the
custom mapper; verify claims before reopening API management traffic.

## Browser and API routes

1. Visit API `/oidc/login`. It first requires reachable group authority.
2. ProxyLens redirects to Keycloak with random state, nonce and S256 challenge.
   The verifier stays server-side; an HttpOnly SameSite=Lax cookie binds state
   to the initiating browser. State is single-use and expires in 300 seconds.
3. `/oidc/callback` validates state/cookie and returned issuer, exchanges the code
   using the public client and verifier, locally validates access and ID tokens,
   checks nonce, matching subject, ID-token authorized party and optional at_hash,
   and checks each claimed group is currently flat/existing.
4. The callback returns verified principal JSON and a CSRF token. An opaque
   HttpOnly cookie refers to a server-side session containing only the original
   access JWT and CSRF secret. `/api/me` revalidates the JWT on every request.
5. Cookie-authenticated unsafe methods need exact `Origin` and
   `X-Proxylens-CSRF` (returned by the callback). `POST /oidc/logout` clears the
   local session. This does not log the user out of Keycloak SSO.

Bearer authentication is also supported by `get_principal`; a supplied malformed
Authorization header never falls back to a cookie. No refresh token is retained.
After at most 300 seconds, re-enter login (Keycloak SSO may avoid another password).
There is no token-returning URL or browser-readable Admin credential. API/OIDC
responses are no-store/no-referrer; the default Uvicorn entrypoint disables access
logs to avoid logging authorization codes. Configure any ingress to redact OIDC
query strings too.

Sessions/login transactions are bounded in-memory stores (4096/1024). Restart
requires re-login. Run one API process; multiworker/HA shared sessions are outside
the single-host phase. They are not an identity authority: sessions retain JWTs,
never a copied role/membership principal. HTTPS uses `__Host-` Secure cookies;
HTTP is accepted only for loopback public URLs. TLS is required for remote users.

## Shared Python contracts

`src/proxylens/identity.py` is the resource/gateway/projection import boundary:

- `Principal`: issuer, validated native subject, roles, group IDs, expiry,
  verification time, signing-key deadline, `verification="keycloak-rs256"`.
- `Capability.READ`, `.USE`, `.MANAGE`; `has_capability`, `in_scope`, `can`,
  `require`. Capabilities and scope are separate tests.
- `get_principal`: FastAPI dependency, using `app.state.identity` from lifespan.
- `get_group_authority`: dependency exposing the read-only `GroupAuthority`.
- `await require_group(principal, capability, group_id, authority)`: scope check;
  USE/MANAGE also require live, active, flat group evidence.

| Role | Read | Use permitted applications | Manage keys/policies | Group scope |
| --- | --- | --- | --- | --- |
| platform-admin | yes | yes | yes | all; target group must exist for use/write |
| group-admin | yes | yes | yes | union of claimed IDs |
| group-member | yes | yes | no | union of claimed IDs |
| auditor | yes | no | no | union of claimed IDs |

Role grants are additive; auditor alone never grants manage/use. Group-admin
applies to **every claimed group**, not a different per-group role. For this phase,
do not assign group-admin to someone who should administer only a subset of their
memberships. Lists/counts/filter/detail consumers must apply the same scope before
querying or returning data. `READ` alone does not validate persisted orphan state;
resource consumers must honor their own durable orphan flags.

Errors: invalid identity 401; scope/CSRF/unusable group 403; unavailable authority
503. Errors expose fixed labels, not tokens, credentials or upstream bodies.

## Outages, expiry and revocation

- RS256 only, fixed configured issuer/API audience/browser authorized party;
  validate signature, sub, iat, exp, optional nbf and typed roles/group claims.
  Required time claims are integer seconds; maximum token lifetime 300 seconds.
- Expiry is strict: **no acceptance at/after exp**. Default 5-second skew applies
  to future iat/nbf only (`PROXYLENS_TOKEN_CLOCK_SKEW`, 0–30).
- Public JWKS cache max/default 300 seconds (`PROXYLENS_JWKS_TTL`, 15–300).
  Refresh serialized and at most once per 15 seconds per process, including
  failures/unknown kids (`PROXYLENS_JWKS_REFRESH_INTERVAL`, 1–TTL). Unknown kid
  during cooldown fails closed; it is never accepted using a different key.
  JWKS refreshes stream at most 65,536 bytes with a two-second whole-refresh
  deadline, reject redirects/compression, and never buffer an unbounded body.
  Bad signatures do not trigger a refresh storm. No stale-key grace beyond TTL.
- Already-authenticated READ requests may continue during outage only with an
  unexpired token and a still-valid cached key. Membership changes/revocation are
  bounded by token expiry, not instant introspection. No group evidence cache.
- New login/callback and every unsafe API request require reachable Admin group
  authority. `require_group` additionally validates target ownership for use/write.
  Gateway machine-key policy and orphan checks are separate integration contracts.
- API readiness includes `keycloak_group_authority` and returns 503 on failure;
  liveness and bounded read behavior are independent of readiness routing.

## Group deletion and resource worker hook

`KeycloakAuthority.lookup_group(id)` performs fresh authenticated Admin reads.
It returns `GroupEvidence(issuer, group_id, ACTIVE|MISSING|NESTED, checked_at)`.
Only authoritative 404 means missing; 401/403/5xx/timeouts/schema mismatch raise
`AuthorityUnavailable`. Same name under a new ID is a different owner.

`await authority.reconcile(group_ids, mark_unusable)` calls the supplied async
hook for missing/nested groups. The resources worker must schedule it, persist
orphan/unusable status and audit evidence transactionally, and block unusable
use. Missing evidence persists `orphaned`; authoritative nested evidence
persists `unusable`. This
identity ticket supplies the detection/hook; it does **not** persist application
orphans or start a resources worker. The hook never auto-clears an orphan or
reassigns ownership. Explicit audited repair/revoke belongs to resource management;
historical ownership stays unchanged. Transient authority failure aborts the scan,
preserving existing flags; retry later. Check ownership live before new use/writes
so a reconciliation interval cannot silently authorize a deleted target.

The worker passes the exact `GroupEvidence` returned by the scan into the resource
repository. The repository does not perform a second active-only lookup, so nested
groups cannot be converted into an outage or lose their transactional audit.

## Verification

Unit/ASGI tests use real RSA signatures and external HTTP mocks. Disposable
rootless Podman Keycloak/PostgreSQL plus Chromium exercised actual browser login,
claims, two-group scope, rename, new-token membership removal, delete/recreate,
nested rejection, signing rotation and outage. See `DEVELOPMENT.md` for precise
evidence and remaining limits. No full-stack provider/usage completion is implied.
