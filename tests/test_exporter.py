"""Exporter public contracts: typed snapshots, durable jobs and external HTTP."""

import asyncio
import json
import os
from dataclasses import replace
from datetime import timedelta

import pytest

from proxylens.correlation import IngressRequest, Ownership
from proxylens.exporter import Observation, serialize_observation


def observation(**kwargs):
    ingress = IngressRequest.new(Ownership("https://identity.test", "g1", "app1", "key-ref"))
    return Observation(
        ingress=ingress,
        ended_at=ingress.accepted_at + timedelta(seconds=1),
        requested_model="requested-alias",
        resolved_model="resolved-model",
        provider="openai",
        endpoint="responses",
        outcome="succeeded",
        status_code=200,
        **kwargs,
    )


def span_from(payload):
    return json.loads(payload)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def attributes(span):
    return {item["key"]: next(iter(item["value"].values())) for item in span["attributes"]}


def test_unproven_gateway_snapshot_is_one_metadata_only_root_with_ingress_ids():
    obs = observation()
    # An unsafe session never becomes remote text; authoritative ingress ID is the fallback.
    obs = replace(obs, ingress=replace(obs.ingress, session_id="Bearer SESSION_SENTINEL"))
    payload = serialize_observation(obs, reason="proof_disabled")
    span = span_from(payload)
    attrs = attributes(span)
    assert span["traceId"] == obs.ingress.trace_id
    assert span["spanId"] == obs.ingress.generation_id
    assert "parentSpanId" not in span
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["langfuse.session.id"] == str(obs.ingress.request_id)
    assert attrs["langfuse.observation.metadata.usage_state"] == "usage_unproven"
    assert attrs["langfuse.observation.metadata.latency_ms"] == "1000"
    assert "langfuse.user.id" not in attrs
    assert "langfuse.observation.usage_details" not in attrs
    assert "langfuse.observation.cost_details" not in attrs
    assert b"SESSION_SENTINEL" not in payload
    assert b'"input"' not in payload and b'"output"' not in payload


def test_only_verified_subject_and_correlated_exclusive_usage_are_serialized():
    from uuid import UUID

    from proxylens.correlation import (
        CorrelationResult,
        CorrelationStatus,
        TenantUsageGate,
        UsageIdentity,
    )
    from proxylens.exporter import ExclusiveUsage, ExportCost
    from proxylens.identity import Principal

    obs = observation()
    ingress = replace(obs.ingress, owner=replace(obs.ingress.owner, subject="verified-human"))
    principal = Principal(
        issuer=ingress.owner.keycloak_issuer,
        subject="verified-human",
        roles=frozenset(),
        group_ids=frozenset({"g1"}),
        expires_at=int(ingress.accepted_at.timestamp()) + 300,
        verified_at=ingress.accepted_at.timestamp() - 1,
        signing_key_valid_until=ingress.accepted_at.timestamp() + 300,
    )
    result = CorrelationResult(
        UsageIdentity("cpamp", "a" * 64, "cpa", UUID("019b0000-0000-7000-8000-000000000001")),
        CorrelationStatus.CORRELATED,
        ingress,
    )
    obs = replace(
        obs,
        ingress=ingress,
        principal=principal,
        correlation=result,
        usage_gate=TenantUsageGate(True, ()),
        usage=ExclusiveUsage(
            input=80, input_cached_tokens=20, output=40, output_reasoning_tokens=10, total=150
        ),
        cost=ExportCost(amount=0.001, currency="USD", classification="estimated"),
    )
    attrs = attributes(span_from(serialize_observation(obs, reason="usage_complete")))
    assert attrs["langfuse.user.id"] == "verified-human"
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {
        "input": 80,
        "input_cached_tokens": 20,
        "output": 40,
        "output_reasoning_tokens": 10,
        "total": 150,
    }
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"total": 0.001}
    assert attrs["langfuse.observation.metadata.cpamp_event_hash"] == "a" * 64
    no_principal = attributes(
        span_from(serialize_observation(replace(obs, principal=None), reason="usage_complete"))
    )
    assert "langfuse.user.id" not in no_principal
    unproven = attributes(
        span_from(
            serialize_observation(
                replace(obs, usage_gate=TenantUsageGate(False, ("proof_missing",))),
                reason="proof_disabled",
            )
        )
    )
    assert "langfuse.observation.usage_details" not in unproven
    assert "langfuse.observation.cost_details" not in unproven


def test_unknown_cost_partial_usage_and_unsafe_metadata_never_turn_into_fake_facts():
    from proxylens.exporter import ExportError

    obs = observation()
    with pytest.raises(ExportError, match="invalid_metadata_reference"):
        serialize_observation(
            replace(obs, provider="Bearer SECRET_SENTINEL"), reason="gateway_only"
        )
    with pytest.raises(TypeError):
        observation(prompt="PROMPT_SENTINEL")


@pytest.fixture
def database():
    from proxylens.db import Database

    db = Database(
        os.environ.get(
            "PROXYLENS_EXPORTER_TEST_DSN",
            "postgresql://proxylens_test:proxylens_test@127.0.0.1:55432/proxylens_exporter",
        )
    )

    async def prepare():
        await db.migrate()
        async with db.transaction() as conn:
            await conn.execute("TRUNCATE exporter_outbox, exporter_counters")

    asyncio.run(prepare())
    return db


def test_finalized_job_survives_restart_and_first_claim_freezes_enrichment(database):
    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings

    async def scenario():
        settings = ExporterSettings(enabled=True)
        repo = ExportRepository(database, settings)
        obs = observation()
        now = obs.ended_at
        first = await repo.enqueue(obs, now=now)
        assert first.state == "READY"  # Proof disabled: finalized gateway-only.
        replay = await repo.enqueue(obs, now=now)
        assert replay.payload_hash == first.payload_hash
        restarted = ExportRepository(database, settings)
        lease = await restarted.claim(now=now)
        assert lease.request_id == obs.ingress.request_id
        assert lease.payload == serialize_observation(obs, reason="proof_disabled")
        assert await repo.claim(now=now) is None
        late = await repo.finalize(
            replace(obs, resolved_model="late-model"), reason="gateway_only", now=now
        )
        assert late.state == "IN_FLIGHT"
        assert late.remote_snapshot_stale is True
        assert late.payload_hash == first.payload_hash
        assert (await repo.stats(now=now))["rows"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("body", "expected", "code"),
    [
        (b'{"id":"queue-job","data":{"ignored":"RESPONSE_SENTINEL"}}', "ACCEPTED", "accepted"),
        (
            b'{"partialSuccess":{"rejectedSpans":"0","errorMessage":"RESPONSE_SENTINEL"}}',
            "ACCEPTED",
            "accepted_warning",
        ),
        (b'{"partialSuccess":{"rejectedSpans":1}}', "DEAD_LETTER", "partial_rejection"),
        (b'{"partialSuccess":{"rejectedSpans":2}}', "UNCERTAIN", "malformed_success"),
        (b'{"partialSuccess":{"rejectedSpans":-1}}', "UNCERTAIN", "malformed_success"),
        (b'{"partialSuccess":{"rejectedSpans":true}}', "UNCERTAIN", "malformed_success"),
        (b'{"partialSuccess":{"rejectedSpans":0.5}}', "UNCERTAIN", "malformed_success"),
        (b'{"partialSuccess":null}', "UNCERTAIN", "malformed_success"),
        (b'{"partialSuccess":{"errorMessage":3}}', "UNCERTAIN", "malformed_success"),
        (b"[]", "UNCERTAIN", "malformed_success"),
        (b"{", "UNCERTAIN", "malformed_success"),
        (b"{}" + b" " * 1000, "UNCERTAIN", "response_limit"),
    ],
)
def test_otlp_success_contract_never_retries_partial_or_ambiguous_acceptance(
    tmp_path,
    body,
    expected,
    code,
):
    import httpx

    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import OtlpTransport

    public = tmp_path / "public"
    secret = tmp_path / "secret"
    public.write_text("synthetic-public")
    secret.write_text("synthetic-secret")
    settings = ExporterSettings(
        enabled=True, public_key_file=public, secret_key_file=secret, max_response_bytes=512
    )

    def server(request):
        assert request.url.path == "/api/public/otel/v1/traces"
        assert request.headers["x-langfuse-ingestion-version"] == "4"
        assert request.headers["authorization"].startswith("Basic ")
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, content=body)

    async def scenario():
        transport = OtlpTransport(settings, transport=httpx.MockTransport(server))
        result = await transport.send(serialize_observation(observation(), reason="proof_disabled"))
        assert result.state == expected
        assert result.code == code
        assert "RESPONSE_SENTINEL" not in repr(result)
        assert "synthetic-secret" not in repr(transport)

    asyncio.run(scenario())


def test_safe_retry_survives_worker_restart_with_frozen_payload_and_bounded_backoff(
    database, tmp_path
):
    import httpx

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import OtlpTransport
    from proxylens.exporter_worker import ExportWorker

    public = tmp_path / "public"
    secret = tmp_path / "secret"
    public.write_text("synthetic-public")
    secret.write_text("synthetic-secret")
    settings = ExporterSettings(enabled=True, public_key_file=public, secret_key_file=secret)
    calls = []

    def server(request):
        calls.append(request.content)
        if len(calls) == 1:
            raise httpx.ConnectError("FAILURE_BODY_SENTINEL", request=request)
        return httpx.Response(200, json={"id": "queue-job"})

    async def scenario():
        obs = observation()
        now = obs.ended_at
        repo = ExportRepository(database, settings)
        await repo.enqueue(obs, now=now)
        transport = OtlpTransport(settings, transport=httpx.MockTransport(server))
        worker = ExportWorker(repo, transport, clock=lambda: now, random_fraction=lambda: 1)
        assert await worker.drain(limit=10) == 1
        job = await repo.get(obs.ingress.request_id)
        assert job.state == "RETRY_WAIT" and job.attempts == 1
        assert job.next_attempt_at == now + timedelta(seconds=1)
        assert "FAILURE_BODY_SENTINEL" not in repr(job)
        restarted = ExportWorker(
            ExportRepository(database, settings),
            transport,
            clock=lambda: now + timedelta(seconds=2),
        )
        assert await restarted.drain(limit=10) == 1
        assert calls[0] == calls[1]
        assert (await repo.get(obs.ingress.request_id)).state == "ACCEPTED"
        assert await restarted.drain(limit=10) == 0

    asyncio.run(scenario())


def test_expired_and_foreign_lease_fences_prevent_stale_acknowledgements(database):
    from uuid import uuid4

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import DeliveryResult

    async def scenario():
        repo = ExportRepository(database, ExporterSettings(enabled=True))
        obs = observation()
        now = obs.ended_at
        await repo.enqueue(obs, now=now)
        claims = await asyncio.gather(*(repo.claim(now=now) for _ in range(8)))
        leases = [lease for lease in claims if lease]
        assert len(leases) == 1
        lease = leases[0]
        accepted = DeliveryResult("ACCEPTED", "accepted")
        assert not await repo.finish(replace(lease, token=uuid4()), accepted, now=now)
        assert not await repo.finish(lease, accepted, now=lease.lease_until)
        await repo.recover(now=lease.lease_until)
        job = await repo.get(obs.ingress.request_id)
        assert job.state == "UNCERTAIN" and job.last_code == "lease_expired"
        assert await repo.claim(now=lease.lease_until + timedelta(seconds=1)) is None
        assert not await repo.finish(lease, accepted, now=now)

    asyncio.run(scenario())


def test_waiting_enrichment_deadline_caps_and_retention_are_observable(database):
    from proxylens.correlation import TenantUsageGate
    from proxylens.exporter import ExportError
    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import DeliveryResult

    async def scenario():
        settings = ExporterSettings(
            enabled=True,
            max_spool_rows=1,
            max_age_seconds=100,
            retention_seconds=200,
            usage_wait_seconds=10,
            max_attempts=2,
        )
        repo = ExportRepository(database, settings)
        obs = observation(usage_gate=TenantUsageGate(True, ()))
        now = obs.ended_at
        assert (await repo.enqueue(obs, now=now)).state == "WAITING"
        assert await repo.claim(now=now) is None
        # Repeated scans do not extend the waiting deadline.
        await repo.enqueue(obs, now=now + timedelta(seconds=5))
        lease = await repo.claim(now=now + timedelta(seconds=10))
        attrs = attributes(span_from(lease.payload))
        assert attrs["langfuse.observation.metadata.finalization_reason"] == "usage_timeout"
        with pytest.raises(ExportError, match="spool_capacity"):
            await repo.enqueue(observation(), now=now)
        retry = DeliveryResult("RETRY_WAIT", "connect_failed")
        assert await repo.finish(lease, retry, now=now + timedelta(seconds=10))
        second = await repo.claim(now=now + timedelta(seconds=11))
        assert await repo.finish(second, retry, now=now + timedelta(seconds=11))
        assert (await repo.get(obs.ingress.request_id)).last_code == "attempt_limit"
        assert (await repo.stats())["counters"]["spool_capacity"] == 1
        assert await repo.prune(now=obs.ingress.accepted_at + timedelta(seconds=199)) == 0
        assert await repo.prune(now=obs.ingress.accepted_at + timedelta(seconds=200)) == 1
        # Even after dedup tombstone removal, an expired source cannot resurrect.
        with pytest.raises(ExportError, match="export_age_limit"):
            await repo.enqueue(obs, now=obs.ingress.accepted_at + timedelta(seconds=201))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, "DEAD_LETTER"),
        (401, "DEAD_LETTER"),
        (403, "DEAD_LETTER"),
        (429, "UNCERTAIN"),
        (500, "UNCERTAIN"),
        (502, "UNCERTAIN"),
        (503, "UNCERTAIN"),
        (504, "UNCERTAIN"),
        (302, "UNCERTAIN"),
        (204, "UNCERTAIN"),
    ],
)
def test_untrusted_proxy_statuses_do_not_establish_nonacceptance(tmp_path, status, expected):
    import httpx

    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import OtlpTransport

    key = tmp_path / "synthetic"
    key.write_text("synthetic-key")
    calls = []

    def server(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Location": "https://never-follow.test"}, content=b"RAW_FAILURE_SECRET"
        )

    async def scenario():
        transport = OtlpTransport(
            ExporterSettings(public_key_file=key, secret_key_file=key),
            transport=httpx.MockTransport(server),
        )
        result = await transport.send(b"{}")
        assert result.state == expected
        assert "RAW_FAILURE_SECRET" not in repr(result)
        assert len(calls) == 1

    asyncio.run(scenario())


def test_cache_creation_is_exclusive_and_unknown_cost_is_not_zero():
    from uuid import UUID

    from proxylens.correlation import (
        CorrelationResult,
        CorrelationStatus,
        TenantUsageGate,
        UsageIdentity,
    )
    from proxylens.exporter import ExclusiveUsage, ExportCost, ExportError

    obs = observation()
    obs = replace(
        obs,
        usage_gate=TenantUsageGate(True, ()),
        correlation=CorrelationResult(
            UsageIdentity("cpamp", "b" * 64, "cpa", UUID("019b0000-0000-7000-8000-000000000002")),
            CorrelationStatus.CORRELATED,
            obs.ingress,
        ),
        usage=ExclusiveUsage(
            input=70,
            input_cached_tokens=20,
            input_cache_creation_tokens=10,
            output=40,
            output_reasoning_tokens=10,
            total=150,
        ),
    )
    attrs = attributes(span_from(serialize_observation(obs, reason="usage_complete")))
    assert json.loads(attrs["langfuse.observation.usage_details"])["total"] == 150
    assert "langfuse.observation.cost_details" not in attrs
    assert attrs["langfuse.observation.metadata.cost_classification"] == "unknown"
    assert "estimated" in attrs["langfuse.observation.metadata.sink_cost_policy"] or (
        "estimate" in attrs["langfuse.observation.metadata.sink_cost_policy"]
    )
    partial = replace(
        obs,
        usage=ExclusiveUsage(input=80, total=150),
        cost=ExportCost(amount=1, currency="EUR", classification="estimated"),
    )
    partial_attrs = attributes(span_from(serialize_observation(partial, reason="usage_timeout")))
    assert "langfuse.observation.usage_details" not in partial_attrs
    assert "langfuse.observation.cost_details" not in partial_attrs
    assert partial_attrs["langfuse.observation.metadata.partial_usage_input"] == "80"
    with pytest.raises(ExportError, match="inconsistent_usage"):
        ExclusiveUsage(
            input=100, input_cached_tokens=20, output=50, output_reasoning_tokens=10, total=150
        )


@pytest.mark.parametrize("mode", ["disconnect", "timeout", "cancel"])
def test_post_write_failure_or_cancellation_is_durable_uncertainty(database, tmp_path, mode):
    import httpx

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import OtlpTransport
    from proxylens.exporter_worker import ExportWorker

    key = tmp_path / "key"
    key.write_text("synthetic-key")
    settings = ExporterSettings(
        enabled=True, public_key_file=key, secret_key_file=key, request_timeout_seconds=0.05
    )

    async def scenario():
        received = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def server(request):
            calls.append(request.content)
            received.set()
            if mode == "disconnect":
                raise httpx.RemoteProtocolError("TOKEN_SENTINEL", request=request)
            await release.wait()
            return httpx.Response(200, json={})

        repo = ExportRepository(database, settings)
        obs = observation()
        await repo.enqueue(obs)
        transport = OtlpTransport(settings, transport=httpx.MockTransport(server))
        worker = ExportWorker(repo, transport)
        task = asyncio.create_task(worker.drain())
        await received.wait()
        # Enqueue/finalize continues while sink is held; it never performs HTTP itself.
        assert (await repo.get(obs.ingress.request_id)).state == "IN_FLIGHT"
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert (await repo.get(obs.ingress.request_id)).state == "UNCERTAIN"
        restarted = ExportWorker(ExportRepository(database, settings), transport)
        assert await restarted.drain() == 0
        assert len(calls) == 1
        assert "TOKEN_SENTINEL" not in repr(await repo.get(obs.ingress.request_id))

    asyncio.run(scenario())


def test_trusted_throttle_retry_after_and_age_cap(database, tmp_path):
    import httpx

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import OtlpTransport
    from proxylens.exporter_worker import ExportWorker

    key = tmp_path / "key"
    key.write_text("synthetic-key")
    settings = ExporterSettings(
        enabled=True,
        public_key_file=key,
        secret_key_file=key,
        trusted_pre_admission_429=True,
        max_age_seconds=30,
    )

    async def scenario():
        obs = observation()
        now = obs.ended_at
        repo = ExportRepository(database, settings)
        await repo.enqueue(obs, now=now)

        def response(request):
            return httpx.Response(429, headers={"Retry-After": "10"})

        worker = ExportWorker(
            repo,
            OtlpTransport(settings, transport=httpx.MockTransport(response)),
            clock=lambda: now,
            random_fraction=lambda: 0,
        )
        assert await worker.drain() == 1
        job = await repo.get(obs.ingress.request_id)
        assert job.next_attempt_at == now + timedelta(seconds=10)
        later = now + timedelta(seconds=25)
        worker = ExportWorker(repo, worker.transport, clock=lambda: later)
        assert await worker.drain() == 1
        job = await repo.get(obs.ingress.request_id)
        assert job.state == "DEAD_LETTER" and job.last_code == "age_limit"

    asyncio.run(scenario())


def test_payload_and_spool_byte_caps_disabled_mode_and_ownership_conflict(database):
    from proxylens.exporter import ExportError
    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings

    async def scenario():
        obs = observation()
        disabled = ExportRepository(database, ExporterSettings())
        with pytest.raises(ExportError, match="exporter_disabled"):
            await disabled.enqueue(obs)
        assert await disabled.claim() is None
        tiny = ExportRepository(database, ExporterSettings(enabled=True, max_payload_bytes=100))
        with pytest.raises(ExportError, match="payload_limit"):
            await tiny.enqueue(obs)
        small = ExportRepository(database, ExporterSettings(enabled=True, max_spool_bytes=100))
        with pytest.raises(ExportError, match="spool_capacity"):
            await small.enqueue(obs)
        repo = ExportRepository(database, ExporterSettings(enabled=True))
        await repo.enqueue(obs)
        changed = replace(
            obs,
            ingress=replace(
                obs.ingress, owner=replace(obs.ingress.owner, keycloak_group_id="other-group")
            ),
        )
        with pytest.raises(ExportError, match="identity_conflict"):
            await repo.enqueue(changed)
        assert (await repo.stats())["rows"] == 1
        assert (await repo.stats())["counters"] == {
            "payload_limit": 1,
            "spool_capacity": 1,
            "identity_conflict": 1,
        }

    asyncio.run(scenario())


def test_interpreter_restart_recovers_pending_and_abandoned_attempts(database):
    import sys

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import DeliveryResult

    async def scenario():
        repo = ExportRepository(database, ExporterSettings(enabled=True))
        obs = observation()
        now = obs.ended_at
        await repo.enqueue(obs, now=now)
        # A separate interpreter claims and exits without acknowledgement.
        script = """
import asyncio, os
from datetime import datetime
from proxylens.db import Database
from proxylens.exporter_repository import ExportRepository
from proxylens.exporter_settings import ExporterSettings
async def main():
    repo = ExportRepository(Database(os.environ['DSN']), ExporterSettings(enabled=True))
    lease = await repo.claim(now=datetime.fromisoformat(os.environ['NOW']))
    assert lease is not None
    print(lease.token)
asyncio.run(main())
"""
        dsn = os.environ.get(
            "PROXYLENS_EXPORTER_TEST_DSN",
            "postgresql://proxylens_test:proxylens_test@127.0.0.1:55432/proxylens_exporter",
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            env={**os.environ, "PYTHONPATH": "src", "DSN": dsn, "NOW": now.isoformat()},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
        assert (await repo.get(obs.ingress.request_id)).state == "IN_FLIGHT"
        restarted = ExportRepository(database, ExporterSettings(enabled=True))
        await restarted.recover(now=now + timedelta(seconds=60))
        assert (await restarted.get(obs.ingress.request_id)).state == "UNCERTAIN"
        assert await restarted.claim(now=now + timedelta(seconds=61)) is None
        # Retryable pending work can be picked up by a separate process too.
        second = observation()
        await repo.enqueue(second, now=now)
        lease = await repo.claim(now=now)
        await repo.finish(lease, DeliveryResult("RETRY_WAIT", "connect_failed"), now=now)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            env={
                **os.environ,
                "PYTHONPATH": "src",
                "DSN": dsn,
                "NOW": (now + timedelta(seconds=2)).isoformat(),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
        assert (await restarted.get(second.ingress.request_id)).attempts == 2

    asyncio.run(scenario())


def test_worker_resumed_after_lease_expiry_cannot_start_a_late_send(database, tmp_path):
    import httpx

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import OtlpTransport
    from proxylens.exporter_worker import ExportWorker

    key = tmp_path / "key"
    key.write_text("synthetic-key")
    settings = ExporterSettings(enabled=True, public_key_file=key, secret_key_file=key)

    async def scenario():
        repo = ExportRepository(database, settings)
        obs = observation()
        now = obs.ended_at
        await repo.enqueue(obs, now=now)
        ticks = iter([now, now + timedelta(seconds=61), now + timedelta(seconds=61)])
        calls = []

        def server(request):
            calls.append(request)
            return httpx.Response(200, json={})

        worker = ExportWorker(
            repo,
            OtlpTransport(settings, transport=httpx.MockTransport(server)),
            clock=lambda: next(ticks),
        )
        assert await worker.drain(limit=1) == 0
        assert calls == []
        assert (await repo.get(obs.ingress.request_id)).state == "UNCERTAIN"

    asyncio.run(scenario())


def test_unattempted_draft_accepts_correlated_usage_then_replay_cannot_duplicate(database):
    from uuid import UUID

    from proxylens.correlation import (
        CorrelationResult,
        CorrelationStatus,
        TenantUsageGate,
        UsageIdentity,
    )
    from proxylens.exporter import ExclusiveUsage
    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import DeliveryResult

    async def scenario():
        repo = ExportRepository(database, ExporterSettings(enabled=True))
        obs = observation(usage_gate=TenantUsageGate(True, ()))
        now = obs.ended_at
        assert (await repo.enqueue(obs, now=now)).state == "WAITING"
        enriched = replace(
            obs,
            correlation=CorrelationResult(
                UsageIdentity(
                    "cpamp", "c" * 64, "cpa", UUID("019b0000-0000-7000-8000-000000000003")
                ),
                CorrelationStatus.CORRELATED,
                obs.ingress,
            ),
            usage=ExclusiveUsage(
                input=80, input_cached_tokens=20, output=40, output_reasoning_tokens=10, total=150
            ),
        )
        assert (await repo.enqueue(enriched, now=now)).state == "READY"
        lease = await repo.claim(now=now)
        attrs = attributes(span_from(lease.payload))
        assert json.loads(attrs["langfuse.observation.usage_details"])["total"] == 150
        assert attrs["langfuse.observation.metadata.finalization_reason"] == "usage_complete"
        assert await repo.finish(lease, DeliveryResult("ACCEPTED", "accepted"), now=now)
        replay = await repo.enqueue(enriched, now=now)
        assert not replay.remote_snapshot_stale
        assert await repo.claim(now=now) is None
        assert (await repo.stats())["states"] == {"ACCEPTED": 1}

    asyncio.run(scenario())


def test_equivalent_rehydrated_utc_ingress_does_not_change_identity(database):
    from datetime import timezone

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings

    async def scenario():
        repo = ExportRepository(database, ExporterSettings(enabled=True))
        obs = observation()
        original = await repo.enqueue(obs)
        rehydrated = replace(
            obs,
            ingress=replace(
                obs.ingress,
                accepted_at=(obs.ingress.accepted_at.astimezone(timezone(timedelta(hours=8)))),
            ),
        )
        replay = await repo.enqueue(rehydrated)
        assert replay.payload_hash == original.payload_hash

    asyncio.run(scenario())


def test_missing_native_id_stays_absent_and_cross_request_evidence_is_rejected():
    from proxylens.correlation import CorrelationResult, CorrelationStatus, UsageIdentity
    from proxylens.exporter import ExportError

    obs = observation()
    event = UsageIdentity("cpamp", "d" * 64, "cpa", None)
    result = CorrelationResult(event, CorrelationStatus.PARTIAL, obs.ingress)
    attrs = attributes(
        span_from(serialize_observation(replace(obs, correlation=result), reason="proof_disabled"))
    )
    assert "langfuse.observation.metadata.cpa_request_id" not in attrs
    other = observation()
    with pytest.raises(ExportError, match="lineage_mismatch"):
        serialize_observation(replace(other, correlation=result), reason="proof_disabled")


@pytest.mark.parametrize(
    "body,state",
    [
        (b'{"partialSuccess":{"rejectedSpans":"1"}}', "DEAD_LETTER"),
        (b"{", "UNCERTAIN"),
    ],
)
def test_partial_and_malformed_receipts_persist_without_worker_resend(
    database, tmp_path, body, state
):
    import httpx

    from proxylens.exporter_repository import ExportRepository
    from proxylens.exporter_settings import ExporterSettings
    from proxylens.exporter_transport import OtlpTransport
    from proxylens.exporter_worker import ExportWorker

    key = tmp_path / "key"
    key.write_text("synthetic-key")
    settings = ExporterSettings(enabled=True, public_key_file=key, secret_key_file=key)

    async def scenario():
        repo = ExportRepository(database, settings)
        obs = observation()
        await repo.enqueue(obs)
        calls = []

        def server(request):
            calls.append(request.content)
            return httpx.Response(200, content=body)

        transport = OtlpTransport(settings, transport=httpx.MockTransport(server))
        await ExportWorker(repo, transport).drain()
        assert (await repo.get(obs.ingress.request_id)).state == state
        restarted = ExportWorker(ExportRepository(database, settings), transport)
        assert await restarted.drain() == 0
        assert len(calls) == 1

    asyncio.run(scenario())
