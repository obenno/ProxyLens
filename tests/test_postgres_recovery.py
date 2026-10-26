"""Real populated dump/restore into newly created databases, including key verification."""

import asyncio
import json
import os
from argparse import Namespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from test_recovery import recovery

from proxylens.correlation import IngressRequest, Ownership
from proxylens.db import Database
from proxylens.lineage import LineageRepository
from proxylens.policies import Policy
from proxylens.resources import ResourceRepository, VerifiedGroup


def test_populated_backup_restore_verifies_resources_lineage_and_new_destination(tmp_path):
    dsn = os.environ.get("PROXYLENS_OPS_TEST_DSN")
    if not dsn:
        pytest.fail("PROXYLENS_OPS_TEST_DSN is required for the real recovery drill")
    admin = conninfo_to_dict(dsn)
    source_name = "ops_recovery_source_" + uuid4().hex
    target_name = "ops_recovery_target_" + uuid4().hex
    source = admin | {"dbname": source_name}
    with psycopg.connect(**admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(source_name))
        )
    try:

        async def group(group_id):
            return VerifiedGroup(group_id)

        async def seed():
            db = Database(**source)
            await db.migrate()
            repo = ResourceRepository(db, group)
            app = await repo.create_application(
                "original-group", "recovery-fixture", actor="fixture"
            )
            await repo.set_group_policy(
                "original-group",
                Policy(models=["fixture-model"], providers=["fixture"]),
                actor="fixture",
            )
            key = await repo.create_key(app["id"], actor="fixture")
            request = IngressRequest.new(
                Ownership("issuer", "original-group", app["id"], key.key["id"])
            )
            async with db.transaction() as conn:
                await LineageRepository(conn).record_ingress(request)
            return key, request

        key, request = asyncio.run(seed())
        connection_file = tmp_path / "connection.json"
        recovery.private_write(connection_file, json.dumps(source).encode())
        backup = tmp_path / "backup"
        args = Namespace(
            connection_file=connection_file,
            destination=backup,
            recovery_set="synthetic-drill",
            pg_container=os.environ.get("PROXYLENS_RECOVERY_PG_CONTAINER"),
            engine=os.environ.get("PROXYLENS_RECOVERY_ENGINE", "docker"),
        )
        recovery.backup_postgres(args)
        args.backup = backup
        args.database = target_name
        args.destination = tmp_path / "restore-report"
        recovery.restore_postgres(args)
        report = json.loads((args.destination / "validation.json").read_text())
        assert report["fingerprints_match"] is True
        assert report["rows"] >= 8

        async def verify():
            db = Database(**(admin | {"dbname": target_name}))
            # Applies checksum verification to restored migration metadata too.
            await db.migrate()
            repo = ResourceRepository(db, group)
            resolved = await repo.authorize(
                key.plaintext, model="fixture-model", provider="fixture", body_bytes=1
            )
            assert resolved.identity.group_id == "original-group"
            async with db.transaction() as conn:
                assert await LineageRepository(conn).get_ingress(request.request_id) == request
            assert len(await repo.list_audit(None)) >= 3

        asyncio.run(verify())
        args.destination = tmp_path / "second-report"
        with pytest.raises(recovery.RecoveryError, match="already exists"):
            recovery.restore_postgres(args)
        # Refusing to reuse a database also preserves the original key and lineage.
        asyncio.run(verify())
    finally:
        # Exact names created by this test only. No existing test databases touched.
        with psycopg.connect(**admin, autocommit=True) as conn:
            for name in (target_name, source_name):
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
