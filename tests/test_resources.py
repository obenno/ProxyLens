"""Public resource contracts exercised against disposable real PostgreSQL."""

import asyncio
import json
import os
import sys

import pytest

from proxylens.db import Database, StorageUnavailable
from proxylens.policies import Policy
from proxylens.resources import ResourceError, ResourceRepository, VerifiedGroup

DSN = os.environ.get(
    "PROXYLENS_RESOURCES_TEST_DSN",
    "postgres://proxylens_test:proxylens_test@127.0.0.1:55432/proxylens_resources",
)


async def lookup(group_id):
    return VerifiedGroup(group_id) if group_id in {"g1", "g2"} else None


@pytest.fixture
def database():
    db = Database(DSN)

    async def prepare():
        await db.migrate()
        async with db.transaction() as conn:
            await conn.execute(
                "TRUNCATE resource_audit, resource_rate_windows, resource_client_keys, "
                "resource_applications, resource_group_refs CASCADE"
            )

    asyncio.run(prepare())
    return db


def test_application_and_key_survive_restart_without_revealing_plaintext(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "IDE", actor="alice")
        issued = await repo.create_key(app["id"], actor="alice")
        assert issued.key["group_id"] == "g1"
        assert issued.key["application_id"] == app["id"]
        assert issued.plaintext.startswith(issued.key["prefix"] + "_")
        restarted = ResourceRepository(Database(DSN), lookup)
        resolved = await restarted.resolve_key(issued.plaintext)
        assert resolved.application_id == app["id"]
        assert resolved.group_id == "g1"
        assert resolved.key_id == issued.key["id"]
        rows = await restarted.list_keys(app["id"])
        assert issued.plaintext not in str(rows)
        assert "secret_hash" not in rows[0]
        assert issued.plaintext not in repr(issued)
        async with database.transaction() as conn:
            stored = await (await conn.execute("SELECT * FROM resource_client_keys")).fetchone()
        assert len(stored["secret_hash"]) == 64
        assert issued.plaintext not in str(stored)
        events = await restarted.list_audit({"g1"})
        assert {event["action"] for event in events} == {"application.create", "key.create"}
        assert all(event["actor"] == "alice" and event["outcome"] == "success" for event in events)
        assert issued.plaintext not in str(events)

    asyncio.run(scenario())


def test_verified_group_orphans_and_explicit_reassignment_preserve_history(database):
    async def scenario():
        groups = {"g1", "g2"}

        async def keycloak(group_id):
            return VerifiedGroup(group_id) if group_id in groups else None

        repo = ResourceRepository(database, keycloak)
        with pytest.raises(ResourceError, match="group_missing"):
            await repo.create_application("missing", "bad", actor="alice")
        app = await repo.create_application("g1", "CLI", actor="alice")
        issued = await repo.create_key(app["id"], actor="alice")

        async def outage(_):
            raise TimeoutError()

        with pytest.raises(ResourceError, match="identity_unavailable"):
            await ResourceRepository(database, outage).reconcile_group("g1", actor="operator")
        assert (await repo.get_application(app["id"]))["state"] == "active"
        groups.remove("g1")
        await repo.reconcile_group("g1", actor="operator")
        assert (await repo.get_application(app["id"]))["state"] == "orphaned"
        assert (await repo.list_keys(app["id"]))[0]["state"] == "orphaned"
        with pytest.raises(ResourceError, match="invalid_client_key"):
            await repo.resolve_key(issued.plaintext)
        groups.add("g1")
        with pytest.raises(ResourceError, match="group_orphaned"):
            await repo.create_application("g1", "not implicitly repaired", actor="operator")
        replacement = await repo.reassign_orphan(app["id"], "g2", actor="operator")
        assert replacement["group_id"] == "g2"
        assert replacement["predecessor_id"] == app["id"]
        assert (await repo.get_application(app["id"]))["group_id"] == "g1"
        assert (await repo.list_keys(app["id"]))[0]["state"] == "revoked"
        assert await repo.list_keys(replacement["id"]) == []
        assert (await repo.create_key(replacement["id"], actor="operator")).key["group_id"] == "g2"
        audit = await repo.list_audit(None)
        repair = next(event for event in audit if event["action"] == "application.reassign")
        assert repair["details"]["previous_group_id"] == "g1"
        assert repair["group_id"] == "g2"

    asyncio.run(scenario())


def test_narrowing_policy_defaults_to_deny_and_changes_apply_immediately(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "SDK", actor="alice")
        key = await repo.create_key(app["id"], actor="alice")
        with pytest.raises(ResourceError, match="policy_denied"):
            await repo.authorize(key.plaintext, model="m2", provider="p1", body_bytes=10)
        await repo.set_group_policy(
            "g1",
            Policy(
                models=["m1", "m2"],
                providers=["p1", "p2"],
                max_body_bytes=100,
                timeout_seconds=30,
                key_requests_per_minute=10,
            ),
            actor="alice",
        )
        await repo.set_application_policy(
            app["id"],
            Policy(
                models=["m2", "m3"],
                providers=["p1", "p3"],
                max_body_bytes=200,
                timeout_seconds=10,
                key_requests_per_minute=20,
            ),
            actor="alice",
        )
        allowed = await repo.authorize(key.plaintext, model="m2", provider="p1", body_bytes=100)
        assert allowed.policy.models == frozenset({"m2"})
        assert allowed.policy.providers == frozenset({"p1"})
        assert allowed.policy.max_body_bytes == 100
        assert allowed.policy.timeout_seconds == 10
        assert allowed.policy.key_requests_per_minute == 10
        with pytest.raises(ResourceError, match="policy_denied"):
            await repo.authorize(key.plaintext, model="m3", provider="p1", body_bytes=10)
        with pytest.raises(ResourceError, match="policy_denied"):
            await repo.authorize(key.plaintext, model="m2", provider="p3", body_bytes=10)
        with pytest.raises(ResourceError, match="body_too_large"):
            await repo.authorize(key.plaintext, model="m2", provider="p1", body_bytes=101)
        await repo.set_group_policy("g1", Policy(models=[], providers=["p1"]), actor="alice")
        assert (await repo.effective_policy(app["id"])).models == frozenset()
        with pytest.raises(ResourceError, match="policy_denied"):
            await ResourceRepository(database, lookup).authorize(
                key.plaintext, model="m2", provider="p1", body_bytes=10
            )
        await repo.set_group_policy("g1", Policy(providers=["p1"]), actor="alice")
        assert (await repo.effective_policy(app["id"])).models == frozenset({"m2", "m3"})

    asyncio.run(scenario())


def test_rotation_and_revocation_are_atomic_and_expiry_is_enforced(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "CLI", actor="alice")
        old = await repo.create_key(app["id"], actor="alice")
        new = await repo.rotate_key(app["id"], old.key["id"], actor="alice")
        assert new.plaintext != old.plaintext
        assert (await repo.resolve_key(new.plaintext)).key_id == new.key["id"]
        with pytest.raises(ResourceError, match="invalid_client_key"):
            await ResourceRepository(database, lookup).resolve_key(old.plaintext)
        with pytest.raises(ResourceError, match="key_inactive"):
            await repo.rotate_key(app["id"], old.key["id"], actor="alice")
        await repo.revoke_key(app["id"], new.key["id"], actor="alice")
        with pytest.raises(ResourceError, match="invalid_client_key"):
            await repo.resolve_key(new.plaintext)
        expiring = await repo.create_key(app["id"], actor="alice")
        async with database.transaction() as conn:
            await conn.execute(
                "UPDATE resource_client_keys SET expires_at = clock_timestamp() WHERE id = %s",
                (expiring.key["id"],),
            )
        with pytest.raises(ResourceError, match="invalid_client_key"):
            await repo.resolve_key(expiring.plaintext)
        assert (await repo.list_keys(app["id"]))[-1]["state"] == "expired"
        audit = await repo.list_audit({"g1"})
        assert {event["action"] for event in audit} >= {"key.rotate", "key.revoke"}

    asyncio.run(scenario())


def test_concurrent_rate_ceilings_share_postgres_across_repository_instances(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "shared", actor="alice")
        other = await repo.create_application("g1", "separate", actor="alice")
        keys = [await repo.create_key(app["id"], actor="alice") for _ in range(2)]
        other_key = await repo.create_key(other["id"], actor="alice")
        await repo.set_group_policy(
            "g1",
            Policy(
                models=["m1"],
                providers=["p1"],
                application_requests_per_minute=3,
                key_requests_per_minute=2,
            ),
            actor="alice",
        )

        async def request(key):
            try:
                await ResourceRepository(database, lookup).authorize(
                    key.plaintext, model="m1", provider="p1", body_bytes=1
                )
                return "allowed"
            except ResourceError as error:
                return error.code

        results = await asyncio.gather(*(request(keys[i % 2]) for i in range(16)))
        assert results.count("allowed") == 3
        assert results.count("rate_limited") == 13
        assert await request(other_key) == "allowed"
        async with database.transaction() as conn:
            counts = await (
                await conn.execute(
                    "SELECT scope, count FROM resource_rate_windows WHERE scope LIKE 'key:%'"
                )
            ).fetchall()
        assert all(row["count"] <= 2 for row in counts)

    asyncio.run(scenario())


def test_audit_failure_rolls_back_key_rotation_and_ownership_mismatch_is_rejected(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "atomic", actor="alice")
        old = await repo.create_key(app["id"], actor="alice")
        before = await repo.list_audit(None)
        async with database.transaction() as conn:
            await conn.execute(
                "ALTER TABLE resource_audit ADD CONSTRAINT test_reject_rotation "
                "CHECK (action <> 'key.rotate') NOT VALID"
            )
        try:
            with pytest.raises(StorageUnavailable):
                await repo.rotate_key(app["id"], old.key["id"], actor="alice")
        finally:
            async with database.transaction() as conn:
                await conn.execute(
                    "ALTER TABLE resource_audit DROP CONSTRAINT test_reject_rotation"
                )
        assert len(await repo.list_keys(app["id"])) == 1
        assert (await repo.resolve_key(old.plaintext)).key_id == old.key["id"]
        assert await repo.list_audit(None) == before
        await repo.create_application("g2", "other", actor="alice")
        with pytest.raises(StorageUnavailable):
            async with database.transaction() as conn:
                await conn.execute(
                    "UPDATE resource_client_keys SET group_id = 'g2' WHERE id = %s",
                    (old.key["id"],),
                )
        assert (await repo.resolve_key(old.plaintext)).group_id == "g1"

    asyncio.run(scenario())


def test_concurrent_rotation_has_one_winner_and_committed_revocation_is_process_visible(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "race", actor="alice")
        old = await repo.create_key(app["id"], actor="alice")
        results = await asyncio.gather(
            *(
                ResourceRepository(Database(DSN), lookup).rotate_key(
                    app["id"], old.key["id"], actor="alice"
                )
                for _ in range(8)
            ),
            return_exceptions=True,
        )
        winners = [result for result in results if not isinstance(result, Exception)]
        assert len(winners) == 1
        assert all(
            isinstance(result, ResourceError) and result.code == "key_inactive"
            for result in results
            if isinstance(result, Exception)
        )
        assert len(await repo.list_keys(app["id"])) == 2
        await repo.revoke_key(app["id"], winners[0].key["id"], actor="alice")
        after_commit = await asyncio.gather(
            *(
                ResourceRepository(Database(DSN), lookup).resolve_key(winners[0].plaintext)
                for _ in range(12)
            ),
            return_exceptions=True,
        )
        assert all(
            isinstance(result, ResourceError) and result.status == 401 for result in after_commit
        )

    asyncio.run(scenario())


def test_migrations_are_repeatable_and_rate_window_expires_without_accumulating_rows(database):
    async def scenario():
        await asyncio.gather(Database(DSN).migrate(), Database(DSN).migrate())
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "window", actor="alice")
        key = await repo.create_key(app["id"], actor="alice")
        await repo.set_group_policy(
            "g1", Policy(models=["m1"], providers=["p1"], key_requests_per_minute=1), actor="alice"
        )
        await repo.authorize(key.plaintext, model="m1", provider="p1", body_bytes=1)
        with pytest.raises(ResourceError, match="rate_limited"):
            await repo.authorize(key.plaintext, model="m1", provider="p1", body_bytes=1)
        async with database.transaction() as conn:
            await conn.execute(
                "UPDATE resource_rate_windows "
                "SET window_start = clock_timestamp() - interval '60 seconds'"
            )
        await repo.authorize(key.plaintext, model="m1", provider="p1", body_bytes=1)
        async with database.transaction() as conn:
            rows = await (await conn.execute("SELECT count FROM resource_rate_windows")).fetchall()
        assert rows == [{"count": 1}]

    asyncio.run(scenario())


def test_new_process_resolves_persisted_keys_and_rejects_committed_revocation(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app = await repo.create_application("g1", "process", actor="alice")
        key = await repo.create_key(app["id"], actor="alice")
        # Send the secret on stdin, never command-line arguments or child output.
        program = """
import asyncio, json, os, sys
from proxylens.db import Database
from proxylens.resources import ResourceRepository, ResourceError
async def forbidden_lookup(_):
    raise AssertionError("machine key resolution cannot create identity evidence")
async def run():
    repo = ResourceRepository(Database(os.environ["TEST_DSN"]), forbidden_lookup)
    try:
        identity = await repo.resolve_key(sys.stdin.read())
        print(json.dumps({"group": identity.group_id, "application": identity.application_id}))
    except ResourceError as error:
        print(json.dumps({"error": error.code}))
asyncio.run(run())
"""

        async def fresh_process():
            child = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                program,
                env={**os.environ, "PYTHONPATH": "src", "TEST_DSN": DSN},
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await child.communicate(key.plaintext.encode())
            assert child.returncode == 0, stderr.decode()
            assert key.plaintext.encode() not in stdout + stderr
            return json.loads(stdout)

        assert await fresh_process() == {"group": "g1", "application": app["id"]}
        await repo.revoke_key(app["id"], key.key["id"], actor="alice")
        assert await fresh_process() == {"error": "invalid_client_key"}

    asyncio.run(scenario())


@pytest.mark.parametrize("token", ["", "Bearer unknown", "plk_000000000000_" + "A" * 43])
def test_missing_malformed_and_unknown_client_keys_are_rejected(database, token):
    async def scenario():
        with pytest.raises(ResourceError, match="invalid_client_key") as failure:
            await ResourceRepository(database, lookup).resolve_key(token)
        assert failure.value.status == 401

    asyncio.run(scenario())
