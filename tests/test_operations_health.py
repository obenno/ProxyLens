import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from proxylens.app import worker_operations_ready
from proxylens.cpamp import AdapterHealth, CollectorStatus, CPAMPAdapter
from proxylens.operations_health import ExportHealth, ProjectionHealth, operations_health

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
