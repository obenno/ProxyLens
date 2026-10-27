# Applications, client keys, and policies

## Integration contract

`proxylens.db.Database` supplies a fresh real PostgreSQL transaction per operation.
Construct with a psycopg DSN or keyword connection options. Run `await db.migrate()`
at startup **before readiness**. It loads packaged `migrations/**/*.sql`, serializes
startup with a PostgreSQL advisory lock, verifies applied SHA256 checksums, and
commits all new migrations atomically. Resources own `009_resources*.sql`.

`ResourceRepository(db, group_lookup)` owns resource persistence, not human
authentication. `group_lookup` is async: return `VerifiedGroup(stable_group_id)`
only after authoritative Keycloak verification of an existing flat group; return
`None` only for authoritative not-found. Raise on timeout, denied Admin access,
malformed results, nested groups, or upstream errors. A request body, boolean,
JWT claim, display name, or path is **not** positive group-existence evidence.
No local user or membership tables exist.

Issue #5 owns authentication. `install_resource_routes(app, repository,
principal_dependency=..., access=ResourceAccess(...))` installs management routes
using its actual verified principal dependency and role/scope adapter. The adapter
provides `actor`, `read_groups`, `can_manage(principal, group_id)`,
`is_platform_admin`, and `can_audit`. Only the explicit platform capability grants
cross-group access; `read_groups=None` cannot bypass it. Group administration must
use #5's actual group-role mapping, not a global group-admin role copied from an
unrelated group. No JWT decoder/verifier exists in this module.

The API lifecycle installs this router with the Keycloak-backed principal and group
lookup adapters. Migration startup and joint identity/resource tests cover the
integration boundary; live provider and tenant-usage proof remain separate gates.

## Gateway-facing Python boundary (#7)

- `await repository.resolve_key(plaintext)` → `ResolvedKey(key_id,
  application_id, group_id, expires_at)`. Only active, unexpired keys belonging to
  active applications and non-orphaned group references resolve. No secret is
  returned or cached. Hash lookup, lifecycle, exact composite ownership FK, and
  policy snapshot are checked on a fresh connection.
- `await repository.effective_policy(application_id)` → immutable
  `EffectivePolicy`, including `group_version` and `application_version`.
- **Dispatch:** `await repository.authorize(plaintext, model=verified_model,
  provider=verified_provider, body_bytes=actual_size)` →
  `Authorization(identity=ResolvedKey, policy=EffectivePolicy)` after committing
  any rate reservations. This revalidates key/lifecycle and policy together;
  do not compose cached resolution with cached policy. Caller headers never supply
  application/group IDs. Gateway must prove alias/provider resolution before this
  call and enforce the returned timeout while forwarding.
- `ResourceError.code/status`: `invalid_client_key` 401, `policy_denied` 403,
  `body_too_large` 413, `rate_limited` 429. `StorageUnavailable` means fail closed
  with 503. No database details or key value are included in errors.
- Authorization has no provider side effects. Gateway must separately **commit
  durable request lineage before dispatch**, using these resolved IDs and policy
  versions. A rate reservation can remain consumed when later lineage/dispatch
  fails; no provider retry or compensating rate decrement is automatic.
- Requests whose authorization read begins after committed revocation/policy
  update see it immediately across processes. An authorization already underway
  uses its read snapshot; in-flight requests are not cancelled or relabeled.
  Gateway should authorize immediately before lineage/dispatch, not at session
  establishment. Group-deletion discovery and evidence-freshness/outage policy
  come from #5's reconciliation integration; this module does not manufacture
  freshness or query Keycloak on every machine request.

## Resource and policy rules

Applications have one immutable owning group reference. Every key derives its
group from its application; `(application_id, group_id)` is a composite foreign
key. Create/rotation/policy mutation verifies group existence before its database
transaction, then rejects a concurrently recorded orphan under row lock.

Keys have an independent non-secret `plk_<12 hex>` prefix and **256 random secret
bits**. Only SHA256 of the full token is stored. Create and rotation return
`{key: metadata, plaintext: token}` once, after commit, with `Cache-Control:
no-store`. Lists/audits/repr never contain plaintext or the hash. Lost issuance
responses cannot be recovered; explicitly revoke/rotate the issued credential.

Expiry is `expires_at <= PostgreSQL clock_timestamp()`; a null expiry is unlimited.
Expiry input must be timezone-aware and future. Rotation atomically revokes the
old key, creates the replacement, and writes both audit events, with **no overlap**.
Repeated/concurrent rotation has exactly one winner. Revocation is idempotent and
each successful management attempt is audited. Failed audit persistence rolls
back the entire mutation. Disabled/revoked/orphaned applications cannot resolve.

Policies are full-replacement PUTs, not patches:

- `models` and `providers`: absent/null = no constraint at that level; `[]` = deny
  all. Intersect every explicitly specified list. No specified list for a dimension
  yields the empty set, hence deny. Both model and provider must be allowed.
- A broader application list is stored but **clipped** by group policy at use time.
  Example group `{m1,m2}`, application `{m2,m3}` → `{m2}`. Group changes immediately
  affect all applications; no policy cache exists.
- `max_body_bytes`, `timeout_seconds`, `key_requests_per_minute`, and
  `application_requests_per_minute`: minimum of specified positive integer
  ceilings; absent everywhere = no resource-level ceiling. Gateway still supplies
  its infrastructure body/time safety limits. Unknown policy fields are rejected.
- Rate limits use PostgreSQL atomic upserts, shared across processes. Each
  application/key has a 60-second window starting with its first admitted request,
  reset on its next admitted request at/after expiry. This is a fixed-window rate,
  not a sliding window or simultaneous-in-flight cap. Application and key counters
  commit together or both roll back. One row per limited resource bounds storage;
  ops retention may prune rows for removed resources. Rotating a key resets its key
  budget but does not reset the application's budget.

## HTTP routes and scope

All paths are under `/api`; successful reads return JSON. Create/rotation/repair
return 201; other successful operations return 200. Authenticated scope denial
returns 403 for mutation and concealed 404 for detail/filter reads. Missing resource
is 404; lifecycle conflict 409; validation 422; unavailable identity/storage 503.
Resource errors use `{"error":"stable_code"}`; schema validation uses FastAPI's
standard 422 envelope. All resource responses are `no-store`.

| Route | Scope |
|---|---|
| `POST /applications` (`group_id`, `name`) | Group administrator or platform administrator |
| `GET /applications?group_id=&limit=&offset=` | Validated readable group union; platform all |
| `GET /applications/{id}` | Owning-group read |
| `GET /applications/{id}/keys` | Owning-group read; metadata only |
| `POST /applications/{id}/keys` (`expires_at`, optional) | Owning-group administrator |
| `POST /applications/{id}/keys/{key}/rotate` | Owning-group administrator |
| `POST /applications/{id}/keys/{key}/revoke` | Owning-group administrator |
| `PUT /groups/{group}/policy` | Group administrator |
| `PUT /applications/{id}/policy` | Owning-group administrator |
| `GET /applications/{id}/effective-policy` | Owning-group read |
| `GET /resource-audit?group_id=&limit=&offset=` | Scoped auditor/administrator; platform all |
| `POST /groups/{group}/reconcile` | Platform administrator |
| `POST /applications/{id}/revoke` | Owning-group administrator or platform administrator |
| `POST /applications/{id}/reassign` (`target_group_id`) | Platform administrator |

Explicitly authorized platform administrators may operate across groups but cannot
create resources for nonexistent groups. Members/auditors cannot mutate resources.
List pagination applies **after** group scope filtering. Repository methods are
trusted internal interfaces; callers exposing them must apply these identity rules.

## Orphans and historical ownership

An authoritative reconciliation not-found marks the group reference and its active
or disabled applications orphaned atomically, blocking all new key resolution.
Dependency errors leave state untouched and fail closed. A later same-name group
or even a recovered lookup does not silently reactivate resources.

Explicit repair creates a **new application ID** in the verified target group,
copies name/application policy, records `predecessor_id`, revokes every old key,
and leaves the original application and keys under their original group forever.
New keys must be issued separately. Original request/usage ownership never moves.
Repair is only allowed from orphaned state; same-group repair is rejected. Explicit
application revocation is also available for orphans. Both operations are atomic
with audit events; old/new group/application references are recorded.

Audit fields: `id`, `actor` (verified subject, null when unknown), `group_id`,
`resource_id`, `action`, `occurred_at` (PostgreSQL UTC-aware timestamp), `outcome`
(`success`/`denied`), safe `details`. No key material, arbitrary request bodies, or
upstream failure strings are stored. Authentication denials have honest null
actor/group/resource. Scoped audit readers cannot see another group's events.
Audit-storage failure returns 503; it never permits a mutation.

Gateway policy, scope, key, group, and rate denials use the same redacted audit
boundary before a response is returned. Machine-key requests have no verified human
actor, so their audit actor is null; group and application references are included
only after the key has resolved them. A denial audit failure returns a generic 503
and never forwards the request.

## Local verification

Run against the dedicated disposable PostgreSQL database (not production):

```sh
PROXYLENS_RESOURCES_TEST_DSN=postgresql://proxylens_test:proxylens_test@127.0.0.1:55432/proxylens_resources \
  python -m pytest tests/test_resources.py tests/test_resource_routes.py -q
```

Fixtures apply production migrations and truncate resource tables in this dedicated
test database. Tests do not skip when PostgreSQL is unavailable. They cover real
transaction/audit rollback, ownership constraints, process-independent rate and
lifecycle races, plaintext absence, policy changes, orphan repair, role/group scope,
unauthenticated audit, and storage/Keycloak failure. External Keycloak group lookups
and verified principals are injected; JWT verification and live identity remain
the coordinator/#5 integration gate.
