"""Projection seams: actual PostgreSQL + worker; only external HTTP is simulated."""

import asyncio
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql

from proxylens.correlation import IngressRequest, Ownership
from proxylens.cpamp import CPAMPAdapter
from proxylens.db import Database
from proxylens.lineage import LineageRepository
from proxylens.projection import ProjectionRepository, ProjectionWorker, projection_worker_lifespan
from proxylens.projection_settings import ProjectionSettings, load_proof_gate

DSN = os.environ.get(
    "PROXYLENS_PROJECTION_TEST_DSN",
    "postgresql://proxylens_test:proxylens_test@127.0.0.1:55432/proxylens_projection",
)
NOW = 1793000000000
NATIVE = "019a96c4-0c00-7000-8000-0123456789ab"


@pytest.fixture
def database():
    schema = "projection_test_" + uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db = Database(DSN, options=f"-c search_path={schema}")
    asyncio.run(db.migrate())
    try:
        yield db
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def settings(**changes):
    return ProjectionSettings(
        cpamp_instance_id="cpamp-test",
        cpa_instance_id="cpa-test",
        keycloak_issuer="https://identity.example/realms/proxylens",
        **changes,
    )


def proof_files(tmp_path, config, *, kinds=("correlation", "durable_history")):
    """Synthetic, explicit caller evidence; production loader must reject it."""
    artifacts = []
    approvals = set()
    for kind in kinds:
        body = {
            "schema_version": 1,
            "kind": kind,
            "provenance": "synthetic",
            "status": "passed",
            "binding": asdict(config.binding),
            "scenarios": list(config.required_scenarios(kind)),
            "verified_at": "2026-10-26T00:00:00Z",
        }
        path = tmp_path / f"{kind}.json"
        content = json.dumps(body).encode()
        path.write_bytes(content)
        artifacts.append(path)
        approvals.add(hashlib.sha256(content).hexdigest())
    return artifacts, approvals


def synthetic_gate(tmp_path, config):
    paths, approvals = proof_files(tmp_path, config)
    return load_proof_gate(config, paths, approved_sha256=approvals, allow_synthetic=True)


def test_proof_requires_both_reviewed_artifacts_and_exact_deployment_binding(tmp_path):
    config = settings()
    assert not load_proof_gate(config).enabled
    paths, approvals = proof_files(tmp_path, config)
    assert not load_proof_gate(config, paths, approved_sha256=approvals).enabled
    assert not load_proof_gate(config, paths, allow_synthetic=True).enabled
    assert not load_proof_gate(
        config,
        paths[:1],
        approved_sha256=approvals,
        allow_synthetic=True,
    ).enabled
    assert load_proof_gate(
        config,
        paths,
        approved_sha256=approvals,
        allow_synthetic=True,
    ).enabled
    other = ProjectionSettings("another-store", "cpa-test", config.keycloak_issuer)
    assert not load_proof_gate(
        other,
        paths,
        approved_sha256=approvals,
        allow_synthetic=True,
    ).enabled
    paths[0].write_text('{"tenant_usage_enabled": true}')
    assert not load_proof_gate(
        config,
        paths,
        approved_sha256=approvals,
        allow_synthetic=True,
    ).enabled


def event(number=1, *, timestamp=NOW - 1000, request_id=NATIVE):
    return {
        "event_hash": f"{number:064x}",
        "request_id": request_id,
        "timestamp_ms": timestamp,
        "failed": False,
        "auth_provider_snapshot": "codex",
        "model": "alias",
        "requested_model": "alias",
        "resolved_model": "model-resolved",
        "input_tokens": 100,
        "output_tokens": 40,
        "cached_tokens": 0,
        "cache_read_tokens": 20,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 10,
        "total_tokens": 140,
    }


class History:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []
        self.status = 200
        self.coverage = None

    def __call__(self, request):
        self.calls.append(request)
        assert "usage-queue" not in request.url.path
        if self.status != 200:
            return httpx.Response(self.status, text="SECRET upstream error")
        if request.url.path.endswith("/export"):
            return httpx.Response(200, text="".join(json.dumps(r) + "\n" for r in self.rows))
        body = json.loads(request.content)
        rows = sorted(
            [r for r in self.rows if body["from_ms"] <= r["timestamp_ms"] < body["to_ms"]],
            key=lambda r: (r["timestamp_ms"], r["event_hash"]),
            reverse=True,
        )
        result = {
            "generated_at_ms": NOW,
            "events": {
                "items": rows,
                "has_more": False,
                "next_before_ms": 0,
                "next_before_id": 0,
                "total_count": len(rows),
            },
        }
        if self.coverage is not None:
            result["coverage"] = self.coverage
        return httpx.Response(200, json=result)


def adapter(history, config, clock):
    return CPAMPAdapter(
        "http://cpamp.example",
        "synthetic-admin",
        instance_id=config.cpamp_instance_id,
        transport=httpx.MockTransport(history),
        clock_ms=lambda: clock[0],
    )


def test_worker_replays_and_restarts_without_double_counting_or_inventing_empty(database, tmp_path):
    async def scenario():
        config = settings(retention_days=1)
        clock = [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        history = History([event()])
        assert (await repo.health())["state"] == "unavailable"
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(repo, source, clock_ms=lambda: clock[0])
            assert not await worker.poll_once()
            assert history.calls == []  # No proofs: no diagnostic reads enable publication.
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            )
            assert await worker.poll_once()
            first = await repo.diagnostic_records()
            assert len(first) == 1
            assert first[0]["event_hash"] == "0" * 63 + "1"
            assert first[0]["correlation_status"] == "partial"
            assert first[0]["group_id"] is None
            assert first[0]["raw_tokens"]["input_tokens"] == 100
            assert first[0]["normalized"]["buckets"] == {
                "input_uncached": 80,
                "cache_read": 20,
                "cache_write": 0,
                "output_nonreasoning": 30,
                "reasoning": 10,
            }
            assert first[0]["cost"]["amount"] is None
            assert first[0]["source"] == "cpamp.analytics"
            assert first[0]["cpamp_version"] == "v1.14.9"
            assert await worker.poll_once()
        restarted = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        assert await restarted.diagnostic_records() == first
        health = await restarted.health()
        assert health["last_success_ms"] == NOW
        assert health["coverage"] == "unknown"
        assert health["state"] == "degraded"  # Native exists, ingress absent.
        assert health["duplicate_count"] == 1

    asyncio.run(scenario())


async def bind(database, group="g1", application="app1", native=NATIVE):
    request = IngressRequest.new(Ownership(settings().keycloak_issuer, group, application, "key"))
    async with database.transaction() as conn:
        conn.row_factory = psycopg.rows.tuple_row
        lineage = LineageRepository(conn)
        await lineage.record_ingress(request)
        await lineage.bind_response(
            request.request_id,
            "cpa-test",
            [
                ("X-CPA-TRACE-ID", f"20261026000000-a-{native}"),
            ],
        )
    return request


def test_cpamp_reads_and_projection_transitions_write_safe_integration_audits(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        history = History([event()])
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            )
            assert await worker.poll_once()
        async with database.transaction() as conn:
            rows = await (
                await conn.execute(
                    "SELECT action, outcome, details FROM resource_audit "
                    "WHERE action LIKE 'integration.%' ORDER BY occurred_at"
                )
            ).fetchall()
        assert [row["action"] for row in rows] == [
            "integration.cpamp.read",
            "integration.projection.promote",
        ]
        assert all(row["outcome"] == "success" for row in rows)
        assert all("event_hash" not in str(row["details"]) for row in rows)

    asyncio.run(scenario())


def test_late_collision_and_missing_ids_never_use_stale_ownership(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        history = History([event(1), event(2), event(3, request_id=None)])
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        owner = await bind(database)
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            )
            assert await worker.poll_once()
            rows = await repo.diagnostic_records()
            assert [r["correlation_status"] for r in rows] == [
                "correlated",
                "correlated",
                "missing",
            ]
            assert [r["group_id"] for r in rows] == ["g1", "g1", None]
            assert rows[0]["proxylens_request_id"] == str(owner.request_id)
            await bind(database, "g2", "app2")
            # No worker refresh: a live join immediately invalidates previous attribution.
            rows = await repo.diagnostic_records()
            assert [r["correlation_status"] for r in rows] == ["ambiguous", "ambiguous", "missing"]
            assert all(r["group_id"] is None for r in rows)
            assert "uncorrelated_records" in (await repo.health())["reasons"]
            # A conflicting CPAMP identity stays poisoned across later correction/replay.
            history.rows[0]["request_id"] = "019a96c4-0c00-7000-8000-0123456789ac"
            assert await worker.poll_once()
            history.rows[0]["request_id"] = NATIVE
            assert await worker.poll_once()
            assert (await repo.diagnostic_records())[0]["correlation_status"] == "ambiguous"

    asyncio.run(scenario())


def test_freshness_gaps_failures_and_unverified_export_preserve_last_valid_view(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        history = History([event()])
        await bind(database)
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            )
            history.status = 401
            assert not await worker.poll_once()
            assert (await repo.health())["state"] == "unavailable"
            history.status = 200
            assert await worker.poll_once()
            assert (await repo.health())["state"] == "available"
            clock[0] += 60_000
            assert (await repo.health())["state"] == "stale"
            history.status = 500
            assert not await worker.poll_once()
            assert (await repo.health())["last_success_ms"] == NOW
            assert len(await repo.diagnostic_records()) == 1
            assert "SECRET" not in str(await repo.health())
            history.status = 200
            history.coverage = {
                "raw_complete": False,
                "scope": "window",
                "mode": "mixed",
                "raw_deleted_event_count": 2,
            }
            assert await worker.poll_once(rebuild=True)
            assert (await repo.health())["coverage"] == "incomplete"
            history.coverage = None
            assert await worker.poll_once()
            assert (await repo.health())["coverage"] == "incomplete"
            before = await repo.diagnostic_records()
            history.rows = []
            # Valid-line EOF (even empty) cannot establish a complete snapshot.
            assert not await worker.rebuild_from_export()
            assert await repo.diagnostic_records() == before
            assert (await repo.health())["state"] == "stale"

    asyncio.run(scenario())


def test_overlap_late_reconciliation_atomic_failure_and_rebuild_equivalence(database, tmp_path):
    async def scenario():
        config = settings(retention_days=1, window_ms=43_200_000, reconcile_seconds=90)
        clock, history = [NOW], History([event(1)])
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        await bind(database)
        gate = synthetic_gate(tmp_path, config)
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(repo, source, gate=gate, clock_ms=lambda: clock[0])
            assert await worker.poll_once()
            history.rows.extend(
                [event(2, timestamp=NOW - 2000), event(3, timestamp=NOW - 4_000_000)]
            )
            history.rows[0]["resolved_model"] = "corrected-model"
            clock[0] += 30_000
            assert await worker.poll_once()
            assert [r["event_hash"][-1] for r in await repo.diagnostic_records()] == ["1", "2"]
            last_payload = json.loads(history.calls[-1].content)
            assert last_payload["from_ms"] == NOW - 300_000
            assert last_payload["to_ms"] == NOW + 30_000
            before = await repo.diagnostic_records()
            # First rebuild window stages a new record, second window fails transport.
            history.rows.append(event(4, timestamp=NOW - 60_000_000))

            def fail_second(request):
                body = json.loads(request.content)
                if body["from_ms"] >= NOW - 43_200_000:
                    return httpx.Response(500)
                return history(request)

            async with CPAMPAdapter(
                "http://cpamp.example",
                "synthetic",
                instance_id=config.cpamp_instance_id,
                transport=httpx.MockTransport(fail_second),
            ) as failing:
                failed_worker = ProjectionWorker(
                    repo, failing, gate=gate, clock_ms=lambda: clock[0]
                )
                assert not await failed_worker.poll_once(rebuild=True)
            assert await repo.diagnostic_records() == before
            assert (await repo.health())["last_success_ms"] == NOW + 30_000
            clock[0] = NOW + 90_000
            # Restart; periodic retained-history scan discovers arbitrary late arrivals.
            repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
            worker = ProjectionWorker(repo, source, gate=gate, clock_ms=lambda: clock[0])
            assert await worker.poll_once()
            complete = await repo.diagnostic_records()
            assert len(complete) == 4
            assert complete[0]["resolved_model"] == "corrected-model"
            assert await worker.poll_once(rebuild=True)
            assert await repo.diagnostic_records() == complete
            # Rebuild from an empty projection agrees; lineage evidence deliberately survives.
            async with database.transaction() as conn:
                await conn.execute("DELETE FROM projection_records")
            assert await worker.poll_once(rebuild=True)
            assert await repo.diagnostic_records() == complete
            # Local retention excludes old source rows and never resurrects them.
            clock[0] += 86_400_000
            assert await worker.poll_once(rebuild=True)
            assert await repo.diagnostic_records() == []

    asyncio.run(scenario())


def test_clean_poll_does_not_hide_persisted_unknown_tokens_or_expected_arrival_lag(
    database, tmp_path
):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        history = History([event(1, timestamp=NOW - 4_000_000)])
        history.rows[0].pop("input_tokens")
        await bind(database)
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            )
            assert await worker.poll_once()
            assert (await repo.diagnostic_records())[0]["normalized"]["buckets"] is None
            clock[0] += 30_000
            assert await worker.poll_once()  # Old malformed normalization outside overlap.
            assert "normalization_unknown" in (await repo.health())["reasons"]
            request = await bind(database, native="019a96c4-0c00-7000-8000-0123456789ac")
            async with database.transaction() as conn:
                await conn.execute(
                    "UPDATE lineage_ingress SET accepted_at=%s WHERE request_id=%s",
                    (datetime.fromtimestamp((clock[0] - 60_000) / 1000, UTC), request.request_id),
                )
            assert await worker.poll_once()
            health = await repo.health()
            assert health["state"] == "stale"
            assert "expected_usage_lag" in health["reasons"]

    asyncio.run(scenario())


def test_malformed_page_and_count_drift_cannot_publish_staged_rebuild(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        history = History([event()])
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        gate = synthetic_gate(tmp_path, config)
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(repo, source, gate=gate, clock_ms=lambda: clock[0])
            assert await worker.poll_once()
            original = await repo.diagnostic_records()
            history.rows.append({**event(2), "event_hash": "unsafe"})
            assert not await worker.poll_once(rebuild=True)
            assert await repo.diagnostic_records() == original
            history.rows = [event(2)]

            def drift(request):
                response = history(request)
                body = response.json()
                body["events"]["total_count"] = 5
                return httpx.Response(200, json=body)

            async with CPAMPAdapter(
                "http://cpamp.example",
                "synthetic",
                instance_id=config.cpamp_instance_id,
                transport=httpx.MockTransport(drift),
            ) as broken:
                worker = ProjectionWorker(repo, broken, gate=gate, clock_ms=lambda: clock[0])
                assert not await worker.poll_once(rebuild=True)
            assert await repo.diagnostic_records() == original
            assert "count_mismatch" in (await repo.health())["reasons"]

    asyncio.run(scenario())


def test_promotion_database_failure_rolls_back_lineage_and_checkpoint_then_restarts(
    database, tmp_path
):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        history = History([event(1)])
        gate = synthetic_gate(tmp_path, config)
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(repo, source, gate=gate, clock_ms=lambda: clock[0])
            assert await worker.poll_once()
            before = await repo.diagnostic_records()
            async with database.transaction() as conn:
                await conn.execute("""
                    CREATE FUNCTION fail_projection_commit() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'synthetic commit failure'; END $$;
                    CREATE TRIGGER projection_commit_failure BEFORE UPDATE ON projection_sources
                    FOR EACH ROW WHEN (NEW.last_success_ms <> OLD.last_success_ms)
                    EXECUTE FUNCTION fail_projection_commit();
                """)
            history.rows.append(event(2))
            clock[0] += 30_000
            assert not await worker.poll_once()
            assert await repo.diagnostic_records() == before
            assert (await repo.health())["state"] == "stale"
            assert (await repo.health())["last_success_ms"] == NOW
            async with database.transaction() as conn:
                count = await (
                    await conn.execute("SELECT count(*) AS n FROM lineage_usage_event")
                ).fetchone()
                assert count["n"] == 1
                await conn.execute("DROP TRIGGER projection_commit_failure ON projection_sources")
            restarted = ProjectionWorker(repo, source, gate=gate, clock_ms=lambda: clock[0])
            assert await restarted.poll_once()
            assert len(await repo.diagnostic_records()) == 2

    asyncio.run(scenario())


def test_worker_lifecycle_excludes_concurrent_poll_and_cancels_held_http(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def held(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        source = CPAMPAdapter(
            "http://cpamp.example",
            "synthetic",
            instance_id=config.cpamp_instance_id,
            transport=httpx.MockTransport(held),
        )
        gate = synthetic_gate(tmp_path, config)
        async with projection_worker_lifespan(repo, source, gate=gate, clock_ms=lambda: clock[0]):
            await asyncio.wait_for(entered.wait(), 2)
            history = History()
            async with adapter(history, config, clock) as second:
                assert not await ProjectionWorker(repo, second, gate=gate).poll_once()
                assert history.calls == []
        assert cancelled.is_set()
        async with adapter(History([event()]), config, clock) as restarted:
            assert await ProjectionWorker(
                repo, restarted, gate=gate, clock_ms=lambda: clock[0]
            ).poll_once()
            assert len(await repo.diagnostic_records()) == 1

    asyncio.run(scenario())


def test_recent_completion_does_not_hide_old_scan_boundary(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        await bind(database)
        history = History([event()])

        def slow(request):
            clock[0] += 60_000
            return history(request)

        async with CPAMPAdapter(
            "http://cpamp.example",
            "synthetic",
            instance_id=config.cpamp_instance_id,
            transport=httpx.MockTransport(slow),
        ) as source:
            assert await ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            ).poll_once()
            assert (await repo.health())["last_success_ms"] == NOW + 60_000
            assert (await repo.health())["state"] == "stale"

    asyncio.run(scenario())


def test_missing_retained_source_record_never_implies_deletion_or_complete_rebuild(
    database, tmp_path
):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        await bind(database)
        history = History([event()])
        async with adapter(history, config, clock) as source:
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            )
            assert await worker.poll_once()
            history.rows = []
            assert await worker.poll_once(rebuild=True)
            assert len(await repo.diagnostic_records()) == 1
            assert "retained_source_absence" in (await repo.health())["reasons"]
            history.status = 500
            assert not await worker.poll_once()
            history.status = 200
            clock[0] += 30_000
            assert await worker.poll_once()
            assert "retained_source_absence" in (await repo.health())["reasons"]

    asyncio.run(scenario())


def test_same_timestamp_keyset_pages_replay_durably(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        calls = []

        def paged(request):
            page = json.loads(request.content)["include"]["events_page"]
            calls.append(page)
            index = page.get("before_id", 4) - 1
            return httpx.Response(
                200,
                json={
                    "generated_at_ms": NOW,
                    "events": {
                        "items": [event(index)],
                        "total_count": 3,
                        "has_more": index > 1,
                        "next_before_ms": NOW - 1000 if index > 1 else 0,
                        "next_before_id": index if index > 1 else 0,
                    },
                },
            )

        async with CPAMPAdapter(
            "http://cpamp.example",
            "synthetic",
            instance_id=config.cpamp_instance_id,
            page_size=1,
            transport=httpx.MockTransport(paged),
        ) as source:
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: clock[0],
            )
            assert await worker.poll_once()
            assert len(await repo.diagnostic_records()) == 3
            assert calls == [
                {"limit": 1},
                {"limit": 1, "before_ms": NOW - 1000, "before_id": 3},
                {"limit": 1, "before_ms": NOW - 1000, "before_id": 2},
            ]
            assert await worker.poll_once()
            assert len(await repo.diagnostic_records()) == 3
            assert (await repo.health())["duplicate_count"] == 3

    asyncio.run(scenario())


def test_cross_window_conflicting_identity_cannot_hide_in_staging(database, tmp_path):
    async def scenario():
        config = settings(retention_days=1, window_ms=43_200_000)
        repo = ProjectionRepository(database, config, clock_ms=lambda: NOW)

        def changing(request):
            start = json.loads(request.content)["from_ms"]
            row = event(1, timestamp=start + 1)
            return httpx.Response(
                200,
                json={
                    "generated_at_ms": NOW,
                    "events": {
                        "items": [row],
                        "total_count": 1,
                        "has_more": False,
                        "next_before_ms": 0,
                        "next_before_id": 0,
                    },
                },
            )

        async with CPAMPAdapter(
            "http://cpamp.example",
            "synthetic",
            instance_id=config.cpamp_instance_id,
            transport=httpx.MockTransport(changing),
        ) as source:
            worker = ProjectionWorker(
                repo,
                source,
                gate=synthetic_gate(tmp_path, config),
                clock_ms=lambda: NOW,
            )
            assert not await worker.poll_once()
            assert await repo.diagnostic_records() == []
            assert (await repo.health())["state"] == "unavailable"

    asyncio.run(scenario())
