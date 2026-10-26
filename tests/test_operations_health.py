from datetime import UTC, datetime, timedelta

from proxylens.cpamp import AdapterHealth, CollectorStatus
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
