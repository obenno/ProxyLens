import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import psycopg

from proxylens.app import worker_operations_ready
from proxylens.cpamp import AdapterHealth, CollectorStatus, CPAMPAdapter
from proxylens.operations_health import ExportHealth, ProjectionHealth, operations_health

pytest_plugins = ("test_operations",)

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def snapshot(**overrides):
    inputs = dict(
        now=NOW,
        postgres=True,
        keycloak=True,
        cliproxyapi=True,
        adapter=AdapterHealth("available", int(NOW.timestamp() * 1000), ()),
        collector=CollectorStatus("available", (), 0, 0, 0),
        projection=ProjectionHealth(enabled=True, last_success=NOW),
        exporter=ExportHealth(enabled=False),
    )
    return operations_health(**(inputs | overrides))


def test_poll_success_never_claims_queue_completeness_and_disabled_is_explicit():
    result = snapshot()
    assert result["dependencies"]["cpamp"]["queue_coverage"] == "unknown"
    assert result["dependencies"]["langfuse"]["state"] == "disabled"
    assert result["dependencies"]["projection"]["state"] == "available"
    assert result["forwarding_ready"] is True


def test_dependency_failures_do_not_turn_unknown_usage_into_zero_or_block_on_langfuse():
    result = snapshot(
        adapter=AdapterHealth("unavailable", None, ("transport", "SECRET")),
        collector=CollectorStatus("degraded", ("dead_letters", "SECRET"), 0, 0, 4),
        exporter=ExportHealth(
            enabled=True, pending=3, uncertain=1, oldest_pending=NOW - timedelta(days=1)
        ),
    )
    assert result["forwarding_ready"] is True
    assert result["dependencies"]["projection"]["state"] == "stale"
    assert result["dependencies"]["cpamp"]["queue_coverage"] == "unknown"
    assert result["dependencies"]["cpamp"]["dead_letters"] == 4
    assert result["dependencies"]["langfuse"]["state"] == "degraded"
    assert "SECRET" not in str(result)
    assert snapshot(postgres=False)["forwarding_ready"] is False
    assert snapshot(keycloak=False)["forwarding_ready"] is False
    assert snapshot(cliproxyapi=False)["forwarding_ready"] is False


def test_freshness_boundary_and_reported_source_gaps_remain_visible():
    assert (
        snapshot(projection=ProjectionHealth(True, NOW - timedelta(seconds=60)))["dependencies"][
            "projection"
        ]["state"]
        == "stale"
    )
    assert (
        snapshot(projection=ProjectionHealth(True, None))["dependencies"]["projection"]["state"]
        == "unavailable"
    )
    assert (
        snapshot(projection=ProjectionHealth(False, NOW))["dependencies"]["projection"]["state"]
        == "disabled"
    )
    assert (
        snapshot(projection=ProjectionHealth(True, NOW, source_gap=True))["dependencies"][
            "projection"
        ]["state"]
        == "degraded"
    )
    assert (
        snapshot(projection=ProjectionHealth(True, NOW, stale=True))["dependencies"]["projection"][
            "state"
        ]
        == "stale"
    )


def test_worker_readiness_requires_cpamp_adapter_and_collector():
    healthy = snapshot()
    assert worker_operations_ready(healthy) is True
    unavailable = snapshot(adapter=AdapterHealth("unavailable", None, ()))
    assert worker_operations_ready(unavailable) is False
    assert (
        worker_operations_ready(
            snapshot(collector=CollectorStatus("degraded", ("dead_letters",), 0, 0, 1))
        )
        is False
    )
    assert worker_operations_ready(None) is False


def test_checkpoint_status_persists_jsonb_details_on_real_postgres(ops_database):
    from proxylens.app import checkpoint_worker_status

    class Supervisor:
        status = {
            "completion_scan": {
                "state": "available",
                "observed_at": NOW,
            }
        }

    async def scenario():
        await checkpoint_worker_status(ops_database, Supervisor())
        async with ops_database.transaction() as conn:
            row = await (
                await conn.execute(
                    "SELECT state, details FROM operations_status WHERE component=%s",
                    ("completion_scan",),
                )
            ).fetchone()
        assert row["state"] == "available"
        assert row["details"] == {
            "state": "available",
            "observed_at": NOW.isoformat(),
        }

    asyncio.run(scenario())


def test_checkpoint_persists_a_stable_snapshot_during_status_updates(ops_database, monkeypatch):
    from proxylens.app import checkpoint_worker_status

    class Supervisor:
        status = {
            "completion_scan": {"state": "available", "observed_at": NOW},
            "cpamp_status": {"state": "unavailable", "observed_at": NOW.isoformat()},
        }

    async def scenario():
        supervisor = Supervisor()
        first_write = asyncio.Event()
        status_updated = asyncio.Event()
        execute = psycopg.AsyncConnection.execute

        async def pause_first_write(conn, query, *args, **kwargs):
            result = await execute(conn, query, *args, **kwargs)
            if query.startswith("INSERT INTO operations_status") and not first_write.is_set():
                first_write.set()
                await status_updated.wait()
            return result

        monkeypatch.setattr(psycopg.AsyncConnection, "execute", pause_first_write)

        async def update_status():
            await first_write.wait()
            # Runtime ticks replace entries and add new components while writes await I/O.
            supervisor.status["cpamp_status"] = {
                "state": "available",
                "observed_at": NOW.isoformat(),
            }
            supervisor.status["group_reconcile"] = {
                "state": "degraded",
                "observed_at": NOW,
            }
            status_updated.set()

        async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
            tasks.create_task(checkpoint_worker_status(ops_database, supervisor))
            tasks.create_task(update_status())

        async def persisted():
            async with ops_database.transaction() as conn:
                return await (
                    await conn.execute(
                        "SELECT component, state, details FROM operations_status ORDER BY component"
                    )
                ).fetchall()

        assert await persisted() == [
            {
                "component": "completion_scan",
                "state": "available",
                "details": {"state": "available", "observed_at": NOW.isoformat()},
            },
            {
                "component": "cpamp_status",
                "state": "unavailable",
                "details": {"state": "unavailable", "observed_at": NOW.isoformat()},
            },
        ]
        await checkpoint_worker_status(ops_database, supervisor)
        assert await persisted() == [
            {
                "component": "completion_scan",
                "state": "available",
                "details": {"state": "available", "observed_at": NOW.isoformat()},
            },
            {
                "component": "cpamp_status",
                "state": "available",
                "details": {"state": "available", "observed_at": NOW.isoformat()},
            },
            {
                "component": "group_reconcile",
                "state": "degraded",
                "details": {"state": "degraded", "observed_at": NOW.isoformat()},
            },
        ]

    asyncio.run(scenario())


def test_proof_disabled_worker_uses_authenticated_collector_without_reading_history():
    async def scenario():
        calls = []
        online = True

        def server(request):
            calls.append(request.url.path)
            assert request.headers["authorization"] == "Bearer synthetic-manager"
            if not online:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={
                    "collector": {
                        "collector": "running",
                        "lastConsumedAt": 0,
                        "lastInsertedAt": 0,
                        "deadLetters": 0,
                    }
                },
            )

        async with CPAMPAdapter(
            "http://cpamp.example",
            "synthetic-manager",
            instance_id="synthetic",
            transport=httpx.MockTransport(server),
        ) as adapter:
            for online in (True, False, True):
                collector = await adapter.read_status()
                health = snapshot(
                    adapter=adapter.health(),
                    collector=collector,
                    projection=ProjectionHealth(enabled=False),
                )
                assert worker_operations_ready(health) is online
                assert health["dependencies"]["projection"]["state"] == "disabled"
                assert health["dependencies"]["cpamp"]["history_state"] == "disabled"
                assert health["dependencies"]["cpamp"]["history_last_success_ms"] is None
                assert health["dependencies"]["cpamp"]["queue_coverage"] == "unknown"
        assert calls == ["/status", "/status", "/status"]

    asyncio.run(scenario())
