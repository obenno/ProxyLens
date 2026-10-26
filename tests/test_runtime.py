"""Production source scanner, joins and retention on real migrated PostgreSQL."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from test_projection import History, adapter, event, settings, synthetic_gate

from proxylens.correlation import IngressRequest, Ownership
from proxylens.exporter_repository import ExportRepository
from proxylens.exporter_settings import ExporterSettings
from proxylens.lineage import LineageRepository
from proxylens.projection import ProjectionRepository, ProjectionWorker
from proxylens.runtime import CompletionScanner

pytest_plugins = ("test_operations",)

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
NATIVE = "019a96c4-0c00-7000-8000-0123456789ab"


async def completed(db, *, started=NOW, group="g1", native=NATIVE):
    request = replace(
        IngressRequest.new(Ownership(settings().keycloak_issuer, group, "app1", "key1")),
        accepted_at=started,
    )
    async with db.transaction() as conn:
        repo = LineageRepository(conn)
        await repo.record_ingress(request)
        await repo.bind_response(
            request.request_id,
            "cpa-test",
            [("X-CPA-TRACE-ID", "20261026000000-synthetic_" + "a-" + native)],
        )
        await conn.execute(
            "INSERT INTO gateway_lifecycle(request_id, requested_model, routing_model, "
            "routing_provider, group_policy_version, application_policy_version, "
            "completed_at, http_status, outcome) VALUES (%s, 'alias', 'attested-only', "
            "'codex', 1, 1, %s, 200, 'completed')",
            (request.request_id, started + timedelta(seconds=1)),
        )
    return request


async def payload(db, request):
    async with db.transaction() as conn:
        row = await (
            await conn.execute(
                "SELECT payload FROM exporter_outbox WHERE request_id=%s", (request.request_id,)
            )
        ).fetchone()
    span = json.loads(bytes(row["payload"]))["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_completion_scanner_is_restart_safe_and_does_not_invent_resolved_usage(ops_database):
    async def scenario():
        request = await completed(ops_database)
        exporter = ExportRepository(ops_database, ExporterSettings(enabled=True))
        scanner = CompletionScanner(ops_database, settings(), exporter)
        assert await scanner.scan(now=NOW + timedelta(seconds=2)) == 1
        attrs = await payload(ops_database, request)
        assert "langfuse.observation.usage_details" not in attrs
        assert "langfuse.observation.model.name" not in attrs
        assert attrs["langfuse.observation.metadata.outcome"] == "succeeded"
        assert attrs["langfuse.observation.metadata.usage_state"] == "usage_unproven"
        assert "langfuse.user.id" not in attrs
        await CompletionScanner(ops_database, settings(), exporter).scan(
            now=NOW + timedelta(seconds=3)
        )
        assert (await exporter.stats())["rows"] == 1

    asyncio.run(scenario())


def test_scanner_uses_current_unique_join_and_exclusive_buckets(ops_database, tmp_path):
    async def scenario():
        request = await completed(ops_database)
        config = settings(retention_days=1)
        gate = synthetic_gate(tmp_path, config)
        clock = [int((NOW + timedelta(seconds=2)).timestamp() * 1000)]
        history = History([event(timestamp=clock[0] - 1000)])
        projection = ProjectionRepository(ops_database, config, clock_ms=lambda: clock[0])
        async with adapter(history, config, clock) as source:
            assert await ProjectionWorker(
                projection, source, gate=gate, clock_ms=lambda: clock[0]
            ).poll_once()
        exporter = ExportRepository(ops_database, ExporterSettings(enabled=True))
        scanner = CompletionScanner(ops_database, config, exporter, gate=gate)
        await scanner.scan(now=NOW + timedelta(seconds=2))
        attrs = await payload(ops_database, request)
        assert json.loads(attrs["langfuse.observation.usage_details"]) == {
            "input": 80,
            "input_cached_tokens": 20,
            "output": 30,
            "output_reasoning_tokens": 10,
            "total": 140,
        }
        assert attrs["langfuse.observation.model.name"] == "model-resolved"
        await completed(ops_database, group="g2")
        await scanner.scan(now=NOW + timedelta(seconds=3))
        attrs = await payload(ops_database, request)
        assert "langfuse.observation.usage_details" not in attrs
        assert "langfuse.observation.metadata.cpamp_event_hash" not in attrs

    asyncio.run(scenario())
