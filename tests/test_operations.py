"""Operations contracts against isolated real PostgreSQL, never the usage queue."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from proxylens.correlation import IngressRequest, Ownership
from proxylens.db import Database, StorageUnavailable
from proxylens.lineage import LineageRepository
from proxylens.operations import RetentionPolicy, RetentionRunner, retention_cutoffs

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


@pytest.fixture
def ops_database():
    dsn = os.environ.get("PROXYLENS_OPS_TEST_DSN")
    if not dsn:
        pytest.fail("PROXYLENS_OPS_TEST_DSN must name an isolated operations database")
    schema = "ops_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = Database(dsn, options=f"-c search_path={schema} -c statement_timeout=5000")
    asyncio.run(db.migrate())
    try:
        yield db
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


class EmptyParticipant:
    """Foundation fixture: no gateway/projection/outbox tables exist in this schema."""

    def __init__(self, name):
        self.name = name

    async def prune(self, conn, cutoffs):
        return 0


def participants():
    return tuple(EmptyParticipant(name) for name in ("gateway", "projection", "outbox"))


def test_retention_exact_utc_boundary_is_durable_and_audited(ops_database):
    async def scenario():
        cutoff = NOW - timedelta(days=90)
        requests = []
        async with ops_database.transaction() as conn:
            for delta in (-1, 0, 1):
                request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
                await LineageRepository(conn).record_ingress(request)
                await conn.execute(
                    "UPDATE lineage_ingress SET accepted_at = %s WHERE request_id = %s",
                    (cutoff + timedelta(microseconds=delta), request.request_id),
                )
                requests.append(request)
            for delta in (-1, 0, 1):
                await conn.execute(
                    "INSERT INTO resource_audit(id, action, outcome, occurred_at) "
                    "VALUES (%s, 'fixture', 'success', %s)",
                    (uuid4(), NOW - timedelta(days=365) + timedelta(microseconds=delta)),
                )
        runner = RetentionRunner(ops_database, RetentionPolicy(), participants())
        result = await runner.run(now=NOW)
        assert result.lineage_deleted == 1
        assert result.audit_deleted == 1
        async with ops_database.transaction() as conn:
            repo = LineageRepository(conn)
            assert await repo.get_ingress(requests[0].request_id) is None
            assert await repo.get_ingress(requests[1].request_id) is not None
            assert await repo.get_ingress(requests[2].request_id) is not None
            events = await (
                await conn.execute(
                    "SELECT action, details FROM resource_audit ORDER BY occurred_at"
                )
            ).fetchall()
            assert [e["action"] for e in events] == ["fixture", "fixture", "retention.delete"]
            assert events[-1]["details"]["lineage_deleted"] == 1
        restarted = RetentionRunner(ops_database, RetentionPolicy(), participants())
        assert (await restarted.run(now=NOW)).lineage_deleted == 0

    asyncio.run(scenario())


def test_pending_work_and_collision_evidence_prevent_false_reassignment(ops_database):
    async def scenario():
        old = NOW - timedelta(days=91)
        ids = [uuid4() for _ in range(3)]
        native = uuid4()
        async with ops_database.transaction() as conn:
            for number, request_id in enumerate(ids):
                request = IngressRequest.new(Ownership("issuer", f"g{number}", "app", "key"))
                await LineageRepository(conn).record_ingress(request)
                await conn.execute(
                    "UPDATE lineage_ingress SET request_id=%s, accepted_at=%s WHERE request_id=%s",
                    (request_id, old if number != 1 else NOW, request.request_id),
                )
            for request_id in ids[:2]:
                await conn.execute(
                    "INSERT INTO lineage_native_binding VALUES ('cpa', %s, %s, %s)",
                    (native, request_id, old),
                )
            await conn.execute(
                "INSERT INTO lineage_usage_event VALUES ('cpamp', %s, 'cpa', %s, false, %s)",
                ("a" * 64, native, old),
            )
            await conn.execute(
                "INSERT INTO operations_retention_hold VALUES ('outbox', 'pending-job', %s)",
                (ids[2],),
            )
        runner = RetentionRunner(ops_database, RetentionPolicy(), participants())
        assert (await runner.run(now=NOW)).lineage_deleted == 0
        async with ops_database.transaction() as conn:
            row = await (await conn.execute("SELECT * FROM lineage_event_resolution")).fetchone()
            assert row["correlation_status"] == "ambiguous"
            assert row["request_id"] is None
            await conn.execute("DELETE FROM operations_retention_hold")
        assert (await runner.run(now=NOW)).lineage_deleted == 1
        # Both colliding requests expire together, so no surviving event gains an owner.
        result = await runner.run(now=NOW + timedelta(days=91))
        assert result.lineage_deleted == 2
        assert result.events_deleted == 1

    asyncio.run(scenario())


def test_retention_rolls_back_deletion_and_floor_if_audit_fails(ops_database):
    async def scenario():
        async with ops_database.transaction() as conn:
            request = IngressRequest.new(Ownership("issuer", "g", "app", "key"))
            await LineageRepository(conn).record_ingress(request)
            await conn.execute(
                "UPDATE lineage_ingress SET accepted_at=%s", (NOW - timedelta(days=91),)
            )
            await conn.execute(
                "ALTER TABLE resource_audit ADD CONSTRAINT failpoint "
                "CHECK (action != 'retention.delete')"
            )
        runner = RetentionRunner(ops_database, RetentionPolicy(), participants())
        with pytest.raises(StorageUnavailable):
            await runner.run(now=NOW)
        async with ops_database.transaction() as conn:
            assert await LineageRepository(conn).get_ingress(request.request_id) is not None
            assert (
                await (await conn.execute("SELECT * FROM operations_retention_state")).fetchone()
                is None
            )

    asyncio.run(scenario())


def test_source_cutoff_is_exact_and_committed_floors_cannot_move_backwards(ops_database):
    async def scenario():
        policy = RetentionPolicy()
        result = await RetentionRunner(ops_database, policy, participants()).run(now=NOW)
        assert not result.cutoffs.accepts_source(NOW - timedelta(days=90, microseconds=1))
        assert result.cutoffs.accepts_source(NOW - timedelta(days=90))
        # A longer configured lifetime does not resurrect already pruned history.
        longer = RetentionPolicy(request_days=180, projection_days=180, outbox_days=180)
        result = await RetentionRunner(ops_database, longer, participants()).run(now=NOW)
        assert result.cutoffs.request == NOW - timedelta(days=90)
        assert result.cutoffs.projection == NOW - timedelta(days=90)
        assert result.cutoffs.outbox == NOW - timedelta(days=90)

    asyncio.run(scenario())


def test_retention_configuration_rejects_unsafe_values_and_missing_hooks():
    assert (
        RetentionPolicy.from_environment({"PROXYLENS_RETENTION_AUDIT_DAYS": "400"}).audit_days
        == 400
    )
    for value in (0, -1, True, 1.5, 36501):
        with pytest.raises(ValueError):
            RetentionPolicy(request_days=value)
    with pytest.raises(ValueError):
        RetentionPolicy().cutoffs(datetime(2026, 10, 26))
    with pytest.raises(ValueError, match="hooks"):
        RetentionRunner(Database(), RetentionPolicy(), [])


def test_source_identity_rows_use_strict_cutoff_and_reimport_reads_committed_floor(ops_database):
    async def scenario():
        cutoff = NOW - timedelta(days=90)
        async with ops_database.transaction() as conn:
            for digit, delta in enumerate((-1, 0, 1)):
                await conn.execute(
                    "INSERT INTO lineage_usage_event "
                    "(cpamp_instance_id, event_hash, cpa_instance_id, first_seen_at) "
                    "VALUES ('cpamp', %s, 'cpa', %s)",
                    (str(digit) * 64, cutoff + timedelta(microseconds=delta)),
                )
        runner = RetentionRunner(ops_database, RetentionPolicy(), participants())
        assert (await runner.run(now=NOW)).events_deleted == 1
        async with ops_database.transaction() as conn:
            rows = await (
                await conn.execute("SELECT event_hash FROM lineage_usage_event ORDER BY event_hash")
            ).fetchall()
            assert [row["event_hash"] for row in rows] == ["1" * 64, "2" * 64]
            effective = await retention_cutoffs(conn, RetentionPolicy(projection_days=180), now=NOW)
            assert not effective.accepts_source(cutoff - timedelta(microseconds=1))
            assert effective.accepts_source(cutoff)
        assert (await runner.run(now=NOW)).events_deleted == 0

    asyncio.run(scenario())
