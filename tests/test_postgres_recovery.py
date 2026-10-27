"""Real populated dump/restore into newly created databases, including key verification."""

import asyncio
import json
import os
from argparse import Namespace
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from test_projection import History, adapter, event, settings, synthetic_gate
from test_recovery import recovery

from proxylens.correlation import IngressRequest, Ownership
from proxylens.db import Database
from proxylens.exporter import Observation
from proxylens.exporter_repository import ExportRepository
from proxylens.exporter_settings import ExporterSettings
from proxylens.lineage import LineageRepository
from proxylens.policies import Policy
from proxylens.projection import ProjectionRepository, ProjectionWorker
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


def test_restored_projection_checkpoint_and_ambiguous_export_are_not_replayed(tmp_path):
    """Synthetic CPAMP HTTP, real final-schema dump/restore and repository recovery."""
    admin = conninfo_to_dict(os.environ["PROXYLENS_OPS_TEST_DSN"])
    source_name = "ops_final_source_" + uuid4().hex
    target_name = "ops_final_target_" + uuid4().hex
    with psycopg.connect(**admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(source_name))
        )
    try:
        source = admin | {"dbname": source_name}
        now = datetime.now(UTC)
        clock = [int(now.timestamp() * 1000)]
        config = settings(retention_days=1)
        gate = synthetic_gate(tmp_path, config)
        export_config = ExporterSettings(enabled=True)
        native = "019a96c4-0c00-7000-8000-0123456789ab"
        request = replace(
            IngressRequest.new(Ownership(config.keycloak_issuer, "original-group", "app", "key")),
            accepted_at=now - timedelta(seconds=2),
        )
        history = History([event(timestamp=clock[0] - 1000, request_id=native)])

        async def seed():
            db = Database(**source)
            await db.migrate()
            async with db.transaction() as conn:
                lineage = LineageRepository(conn)
                await lineage.record_ingress(request)
                await lineage.bind_response(
                    request.request_id,
                    config.cpa_instance_id,
                    [("X-CPA-TRACE-ID", "20261027000000-synthetic-" + native)],
                )
            projection = ProjectionRepository(db, config, clock_ms=lambda: clock[0])
            async with adapter(history, config, clock) as cpamp:
                assert await ProjectionWorker(
                    projection, cpamp, gate=gate, clock_ms=lambda: clock[0]
                ).poll_once()
            outbox = ExportRepository(db, export_config)
            observation = Observation(
                request, now, "alias", None, None, "responses", "succeeded", 200
            )
            job = await outbox.enqueue(observation, now=now)
            lease = await outbox.claim(now=now)
            assert lease.request_id == request.request_id
            return (
                await projection.diagnostic_records(),
                await projection.source_state(),
                job.payload_hash,
            )

        records, checkpoint, payload_hash = asyncio.run(seed())
        connection = tmp_path / "connection.json"
        recovery.private_write(connection, json.dumps(source).encode())
        args = Namespace(
            connection_file=connection,
            destination=tmp_path / "backup",
            recovery_set="synthetic-final-schema",
            pg_container=os.getenv("PROXYLENS_RECOVERY_PG_CONTAINER"),
            engine=os.getenv("PROXYLENS_RECOVERY_ENGINE", "docker"),
        )
        recovery.backup_postgres(args)
        args.backup = args.destination
        args.database = target_name
        args.destination = tmp_path / "restored"
        recovery.restore_postgres(args)
        assert json.loads((args.destination / "validation.json").read_text())["fingerprints_match"]

        async def verify():
            db = Database(**(admin | {"dbname": target_name}))
            await db.migrate()
            projection = ProjectionRepository(db, config, clock_ms=lambda: clock[0])
            assert await projection.diagnostic_records() == records
            assert await projection.source_state() == checkpoint
            outbox = ExportRepository(db, export_config)
            assert (await outbox.get(request.request_id)).state == "IN_FLIGHT"
            later = now + timedelta(seconds=export_config.lease_seconds + 1)
            await outbox.recover(now=later)
            recovered = await outbox.get(request.request_id)
            assert recovered.state == "UNCERTAIN"
            assert recovered.payload_hash == payload_hash
            assert recovered.attempts == 1
            assert await outbox.claim(now=later) is None
            # Failed source polling retains populated restored facts and checkpoint.
            clock[0] += 60_000
            history.status = 503
            async with adapter(history, config, clock) as cpamp:
                worker = ProjectionWorker(projection, cpamp, gate=gate, clock_ms=lambda: clock[0])
                assert not await worker.poll_once()
                assert (await projection.health())["state"] == "stale"
                assert await projection.diagnostic_records() == records
                assert (await projection.source_state())["last_success_ms"] == checkpoint[
                    "last_success_ms"
                ]
                history.status = 200
                assert await worker.poll_once()
                assert await projection.diagnostic_records() == records
            assert (await outbox.stats(now=later))["states"] == {"UNCERTAIN": 1}

        asyncio.run(verify())
    finally:
        with psycopg.connect(**admin, autocommit=True) as conn:
            for name in (target_name, source_name):
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
