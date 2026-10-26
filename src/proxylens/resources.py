"""Durable resources, without local user or membership authority."""

import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from proxylens.db import Database
from proxylens.policies import EffectivePolicy, Policy, effective_policy


class ResourceError(Exception):
    def __init__(self, code: str, status: int = 403):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class VerifiedGroup:
    """Only construct from a successful authoritative, flat Keycloak group lookup."""

    id: str


GroupLookup = Callable[[str], Awaitable[VerifiedGroup | None]]


@dataclass(frozen=True)
class IssuedKey:
    key: dict
    plaintext: str = field(repr=False)


@dataclass(frozen=True)
class ResolvedKey:
    key_id: str
    application_id: str
    group_id: str
    expires_at: datetime | None


@dataclass(frozen=True)
class Authorization:
    identity: ResolvedKey
    policy: EffectivePolicy


KEY_COLUMNS = (
    "id, application_id, group_id, prefix, created_at, expires_at, revoked_at, "
    "CASE WHEN revoked_at IS NOT NULL THEN 'revoked' "
    "WHEN expires_at <= clock_timestamp() THEN 'expired' ELSE 'active' END AS state"
)


def public(row):
    if row is None:
        raise ResourceError("not_found", 404)
    return {k: str(v) if isinstance(v, UUID) else v for k, v in row.items()}


class ResourceRepository:
    def __init__(self, database: Database, group_lookup: GroupLookup):
        self.database = database
        self.group_lookup = group_lookup

    async def _lookup_group(self, group_id):
        try:
            group = await self.group_lookup(group_id)
        except Exception:
            raise ResourceError("identity_unavailable", 503) from None
        if group is not None and (not isinstance(group, VerifiedGroup) or group.id != group_id):
            raise ResourceError("identity_unavailable", 503)
        return group

    async def _verify_group(self, group_id):
        if await self._lookup_group(group_id) is None:
            raise ResourceError("group_missing", 409)

    async def _group(self, conn, group_id):
        await conn.execute(
            "INSERT INTO resource_group_refs(id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            (group_id,),
        )
        row = await (
            await conn.execute(
                "SELECT * FROM resource_group_refs WHERE id = %s FOR UPDATE", (group_id,)
            )
        ).fetchone()
        if row["state"] != "active":
            raise ResourceError("group_orphaned", 409)
        await conn.execute(
            "UPDATE resource_group_refs SET verified_at = clock_timestamp() WHERE id = %s",
            (group_id,),
        )
        return row

    async def _audit(
        self, conn, action, actor, group_id, resource_id, outcome="success", **details
    ):
        await conn.execute(
            "INSERT INTO resource_audit"
            "(id, actor, group_id, resource_id, action, outcome, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                uuid4(),
                actor,
                group_id,
                str(resource_id) if resource_id else None,
                action,
                outcome,
                Jsonb(details),
            ),
        )

    async def record_denial(self, action, *, actor=None, group_id=None, resource_id=None):
        async with self.database.transaction() as conn:
            await self._audit(conn, action, actor, group_id, resource_id, "denied")

    async def create_application(self, group_id: str, name: str, *, actor: str):
        if not group_id or len(group_id) > 200 or not name.strip() or len(name) > 200:
            raise ResourceError("invalid_application", 422)
        await self._verify_group(group_id)
        async with self.database.transaction() as conn:
            await self._group(conn, group_id)
            row = await (
                await conn.execute(
                    "INSERT INTO resource_applications(id, group_id, name) "
                    "VALUES (%s, %s, %s) RETURNING *",
                    (uuid4(), group_id, name),
                )
            ).fetchone()
            await self._audit(conn, "application.create", actor, group_id, row["id"])
            return public(row)

    async def get_application(self, application_id):
        async with self.database.transaction() as conn:
            return public(
                await (
                    await conn.execute(
                        "SELECT * FROM resource_applications WHERE id = %s", (application_id,)
                    )
                ).fetchone()
            )

    async def list_applications(self, group_ids: set[str] | None, *, limit=100, offset=0):
        async with self.database.transaction() as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM resource_applications "
                    "WHERE (%s::text[] IS NULL OR group_id = ANY(%s)) "
                    "ORDER BY created_at, id LIMIT %s OFFSET %s",
                    (
                        list(group_ids) if group_ids is not None else None,
                        list(group_ids) if group_ids is not None else None,
                        limit,
                        offset,
                    ),
                )
            ).fetchall()
            return [public(row) for row in rows]

    async def _active_application(self, conn, application_id):
        # Group first, then application, then key is the common lifecycle lock order.
        found = await (
            await conn.execute(
                "SELECT group_id FROM resource_applications WHERE id = %s", (application_id,)
            )
        ).fetchone()
        if not found:
            raise ResourceError("not_found", 404)
        await self._group(conn, found["group_id"])
        app = await (
            await conn.execute(
                "SELECT * FROM resource_applications WHERE id = %s FOR UPDATE", (application_id,)
            )
        ).fetchone()
        if app["state"] != "active":
            raise ResourceError("application_inactive", 409)
        return app

    async def _issue(self, conn, app, actor, expires_at):
        if expires_at is not None:
            now = await (await conn.execute("SELECT clock_timestamp() AS now")).fetchone()
            if expires_at.tzinfo is None or expires_at <= now["now"]:
                raise ResourceError("invalid_expiry", 422)
        prefix = "plk_" + secrets.token_hex(6)
        plaintext = prefix + "_" + secrets.token_urlsafe(32)
        row = await (
            await conn.execute(
                "INSERT INTO resource_client_keys"
                "(id, application_id, group_id, prefix, secret_hash, expires_at) "
                f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {KEY_COLUMNS}",
                (
                    uuid4(),
                    app["id"],
                    app["group_id"],
                    prefix,
                    sha256(plaintext.encode()).hexdigest(),
                    expires_at,
                ),
            )
        ).fetchone()
        await self._audit(conn, "key.create", actor, app["group_id"], row["id"])
        return IssuedKey(public(row), plaintext)

    async def create_key(self, application_id, *, actor, expires_at=None):
        app = await self.get_application(application_id)
        await self._verify_group(app["group_id"])
        async with self.database.transaction() as conn:
            app = await self._active_application(conn, application_id)
            return await self._issue(conn, app, actor, expires_at)

    async def reconcile_group(self, group_id, *, actor):
        """Only authoritative absence marks an orphan; dependency errors never do."""
        group = await self._lookup_group(group_id)
        async with self.database.transaction() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM resource_group_refs WHERE id = %s FOR UPDATE",
                    (group_id,),
                )
            ).fetchone()
            if not row:
                raise ResourceError("not_found", 404)
            if group is None:
                await conn.execute(
                    "UPDATE resource_group_refs SET state = 'orphaned' WHERE id = %s", (group_id,)
                )
                await conn.execute(
                    "UPDATE resource_applications SET state = 'orphaned' "
                    "WHERE group_id = %s AND state IN ('active', 'disabled')",
                    (group_id,),
                )
            await conn.execute(
                "UPDATE resource_group_refs SET verified_at = clock_timestamp() WHERE id = %s",
                (group_id,),
            )
            state = "orphaned" if group is None else row["state"]
            await self._audit(conn, "group.reconcile", actor, group_id, group_id, state=state)
            return {"id": group_id, "state": state}

    async def revoke_application(self, application_id, *, actor):
        async with self.database.transaction() as conn:
            app = public(
                await (
                    await conn.execute(
                        "UPDATE resource_applications SET state = 'revoked' "
                        "WHERE id = %s RETURNING *",
                        (application_id,),
                    )
                ).fetchone()
            )
            await conn.execute(
                "UPDATE resource_client_keys "
                "SET revoked_at = COALESCE(revoked_at, clock_timestamp()) "
                "WHERE application_id = %s",
                (application_id,),
            )
            await self._audit(conn, "application.revoke", actor, app["group_id"], application_id)
            return app

    async def reassign_orphan(self, application_id, target_group_id, *, actor):
        """Repair by replacement: immutable historical ownership, no key transfer."""
        await self._verify_group(target_group_id)
        async with self.database.transaction() as conn:
            await self._group(conn, target_group_id)
            old = public(
                await (
                    await conn.execute(
                        "SELECT * FROM resource_applications WHERE id = %s FOR UPDATE",
                        (application_id,),
                    )
                ).fetchone()
            )
            if old["state"] != "orphaned" or old["group_id"] == target_group_id:
                raise ResourceError("not_reassignable", 409)
            replacement = public(
                await (
                    await conn.execute(
                        "INSERT INTO resource_applications"
                        "(id, group_id, name, policy, predecessor_id) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                        (
                            uuid4(),
                            target_group_id,
                            old["name"],
                            Jsonb(old["policy"]),
                            application_id,
                        ),
                    )
                ).fetchone()
            )
            await conn.execute(
                "UPDATE resource_applications SET state = 'revoked' WHERE id = %s",
                (application_id,),
            )
            await conn.execute(
                "UPDATE resource_client_keys "
                "SET revoked_at = COALESCE(revoked_at, clock_timestamp()) "
                "WHERE application_id = %s",
                (application_id,),
            )
            await self._audit(
                conn,
                "application.reassign",
                actor,
                target_group_id,
                replacement["id"],
                previous_group_id=old["group_id"],
                previous_application_id=application_id,
            )
            await self._audit(
                conn,
                "application.revoke",
                actor,
                old["group_id"],
                application_id,
                replacement_id=replacement["id"],
                replacement_group_id=target_group_id,
            )
            return replacement

    async def rotate_key(self, application_id, key_id, *, actor, expires_at=None):
        app = await self.get_application(application_id)
        await self._verify_group(app["group_id"])
        async with self.database.transaction() as conn:
            app = await self._active_application(conn, application_id)
            old = await (
                await conn.execute(
                    "UPDATE resource_client_keys SET revoked_at = clock_timestamp() "
                    "WHERE id = %s AND application_id = %s AND revoked_at IS NULL "
                    "AND (expires_at IS NULL OR expires_at > clock_timestamp()) RETURNING id",
                    (key_id, application_id),
                )
            ).fetchone()
            if not old:
                raise ResourceError("key_inactive", 409)
            issued = await self._issue(conn, app, actor, expires_at)
            await self._audit(
                conn, "key.rotate", actor, app["group_id"], key_id, replacement_id=issued.key["id"]
            )
            return issued

    async def revoke_key(self, application_id, key_id, *, actor):
        app = await self.get_application(application_id)
        async with self.database.transaction() as conn:
            row = await (
                await conn.execute(
                    "UPDATE resource_client_keys "
                    "SET revoked_at = COALESCE(revoked_at, clock_timestamp()) "
                    f"WHERE id = %s AND application_id = %s RETURNING {KEY_COLUMNS}",
                    (key_id, application_id),
                )
            ).fetchone()
            key = public(row)
            await self._audit(conn, "key.revoke", actor, app["group_id"], key_id)
            return key

    async def list_keys(self, application_id):
        async with self.database.transaction() as conn:
            rows = await (
                await conn.execute(
                    f"SELECT {KEY_COLUMNS}, "
                    "EXISTS (SELECT 1 FROM resource_applications a "
                    "JOIN resource_group_refs g ON g.id = a.group_id "
                    "WHERE a.id = resource_client_keys.application_id "
                    "AND (a.state = 'orphaned' OR g.state = 'orphaned')) AS orphaned "
                    "FROM resource_client_keys "
                    "WHERE application_id = %s ORDER BY created_at, id",
                    (application_id,),
                )
            ).fetchall()
            for row in rows:
                if row["state"] == "active" and row["orphaned"]:
                    row["state"] = "orphaned"
            return [public(row) for row in rows]

    async def set_group_policy(self, group_id, policy: Policy, *, actor):
        await self._verify_group(group_id)
        async with self.database.transaction() as conn:
            await self._group(conn, group_id)
            await conn.execute(
                "UPDATE resource_group_refs SET policy = %s, "
                "policy_version = policy_version + 1 WHERE id = %s",
                (Jsonb(policy.model_dump()), group_id),
            )
            await self._audit(conn, "policy.group.update", actor, group_id, group_id)
        return policy

    async def set_application_policy(self, application_id, policy: Policy, *, actor):
        app = await self.get_application(application_id)
        await self._verify_group(app["group_id"])
        async with self.database.transaction() as conn:
            app = await self._active_application(conn, application_id)
            await conn.execute(
                "UPDATE resource_applications SET policy = %s, "
                "policy_version = policy_version + 1 WHERE id = %s",
                (Jsonb(policy.model_dump()), application_id),
            )
            await self._audit(
                conn, "policy.application.update", actor, app["group_id"], application_id
            )
            row = await (
                await conn.execute(
                    "SELECT g.policy AS group_policy, a.policy AS application_policy, "
                    "g.policy_version AS group_version, a.policy_version AS application_version "
                    "FROM resource_applications a JOIN resource_group_refs g ON g.id = a.group_id "
                    "WHERE a.id = %s",
                    (application_id,),
                )
            ).fetchone()
            return self._policy(row)

    @staticmethod
    def _policy(row):
        return effective_policy(
            Policy(**row["group_policy"]),
            Policy(**row["application_policy"]),
            row["group_version"],
            row["application_version"],
        )

    async def effective_policy(self, application_id) -> EffectivePolicy:
        async with self.database.transaction() as conn:
            row = await (
                await conn.execute(
                    "SELECT g.policy AS group_policy, a.policy AS application_policy, "
                    "g.policy_version AS group_version, a.policy_version AS application_version "
                    "FROM resource_applications a JOIN resource_group_refs g ON g.id = a.group_id "
                    "WHERE a.id = %s AND a.state = 'active' AND g.state = 'active'",
                    (application_id,),
                )
            ).fetchone()
            if not row:
                raise ResourceError("application_inactive", 403)
            return self._policy(row)

    async def _resolve(self, conn, plaintext):
        if not re.fullmatch(r"plk_[0-9a-f]{12}_[A-Za-z0-9_-]{43}", plaintext):
            raise ResourceError("invalid_client_key", 401)
        row = await (
            await conn.execute(
                "SELECT k.id, k.application_id, k.group_id, k.expires_at, "
                "g.policy AS group_policy, a.policy AS application_policy, "
                "g.policy_version AS group_version, a.policy_version AS application_version "
                "FROM resource_client_keys k "
                "JOIN resource_applications a "
                "ON (a.id, a.group_id) = (k.application_id, k.group_id) "
                "JOIN resource_group_refs g ON g.id = a.group_id "
                "WHERE k.secret_hash = %s AND k.revoked_at IS NULL "
                "AND (k.expires_at IS NULL OR k.expires_at > clock_timestamp()) "
                "AND a.state = 'active' AND g.state = 'active'",
                (sha256(plaintext.encode()).hexdigest(),),
            )
        ).fetchone()
        if not row:
            raise ResourceError("invalid_client_key", 401)
        return Authorization(
            ResolvedKey(
                str(row["id"]), str(row["application_id"]), row["group_id"], row["expires_at"]
            ),
            self._policy(row),
        )

    async def resolve_key(self, plaintext: str) -> ResolvedKey:
        async with self.database.transaction() as conn:
            return (await self._resolve(conn, plaintext)).identity

    async def authorize(
        self,
        plaintext: str,
        *,
        model: str,
        provider: str,
        body_bytes: int,
        requested_model: str | None = None,
    ) -> Authorization:
        """Validate identity and policy in one fresh database snapshot before dispatch."""
        async with self.database.transaction() as conn:
            result = await self._resolve(conn, plaintext)
            policy = result.policy
            if (
                model not in policy.models
                or provider not in policy.providers
                or (requested_model is not None and requested_model not in policy.models)
            ):
                raise ResourceError("policy_denied", 403)
            if body_bytes < 0:
                raise ResourceError("invalid_body_size", 422)
            if policy.max_body_bytes is not None and body_bytes > policy.max_body_bytes:
                raise ResourceError("body_too_large", 413)
            # Consistent application -> key ordering avoids cross-key deadlocks.
            # Both increments roll back if either limit rejects the request.
            for scope, ceiling in (
                (
                    "application:" + result.identity.application_id,
                    policy.application_requests_per_minute,
                ),
                ("key:" + result.identity.key_id, policy.key_requests_per_minute),
            ):
                if ceiling is None:
                    continue
                admitted = await (
                    await conn.execute(
                        "INSERT INTO resource_rate_windows(scope, window_start, count) "
                        "VALUES (%s, clock_timestamp(), 1) ON CONFLICT (scope) DO UPDATE SET "
                        "count = CASE WHEN resource_rate_windows.window_start "
                        "<= clock_timestamp() - interval '60 seconds' "
                        "THEN 1 ELSE resource_rate_windows.count + 1 END, "
                        "window_start = CASE WHEN resource_rate_windows.window_start "
                        "<= clock_timestamp() - interval '60 seconds' "
                        "THEN clock_timestamp() ELSE resource_rate_windows.window_start END "
                        "WHERE resource_rate_windows.count < %s OR "
                        "resource_rate_windows.window_start <= "
                        "clock_timestamp() - interval '60 seconds' RETURNING count",
                        (scope, ceiling),
                    )
                ).fetchone()
                if not admitted:
                    raise ResourceError("rate_limited", 429)
            return result

    async def list_audit(self, group_ids: set[str] | None, *, limit=100, offset=0):
        async with self.database.transaction() as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM resource_audit WHERE (%s::text[] IS NULL OR group_id = ANY(%s)) "
                    "ORDER BY occurred_at DESC, id LIMIT %s OFFSET %s",
                    (
                        list(group_ids) if group_ids is not None else None,
                        list(group_ids) if group_ids is not None else None,
                        limit,
                        offset,
                    ),
                )
            ).fetchall()
            return [public(row) for row in rows]
