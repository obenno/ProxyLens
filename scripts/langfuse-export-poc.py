#!/usr/bin/env python3
"""Synthetic exporter/live v4 readback proof; credentials are read only from files.

Run with PYTHONPATH=src and a disposable PostgreSQL/Langfuse destination. This
never calls a provider or fabricates CPAMP usage. Output is a small safe summary.
"""

import argparse
import asyncio
import json
import os
import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from proxylens.correlation import IngressRequest, Ownership
from proxylens.db import Database
from proxylens.exporter import Observation
from proxylens.exporter_repository import ExportRepository
from proxylens.exporter_settings import ExporterSettings
from proxylens.exporter_transport import OtlpTransport
from proxylens.exporter_worker import ExportWorker


async def run(args):
    settings = ExporterSettings(
        enabled=True,
        destination="exporter-live-poc",
        base_url=args.base_url,
        public_key_file=args.public_key_file,
        secret_key_file=args.secret_key_file,
        request_timeout_seconds=5,
    )
    db = Database(os.environ["PROXYLENS_EXPORTER_TEST_DSN"])
    await db.migrate()
    repo = ExportRepository(db, settings)
    ingress = IngressRequest.new(
        Ownership("https://synthetic.invalid", "poc-group", "poc-app", "poc-key")
    )
    # Preserve a real original request interval; no content or synthetic usage.
    ingress = replace(ingress, accepted_at=datetime.now(UTC) - timedelta(seconds=1))
    obs = Observation(
        ingress, datetime.now(UTC), "poc-model", None, None, "responses", "succeeded", 200
    )
    await repo.enqueue(obs)

    # An actually bound, non-listening loopback socket establishes connection refusal.
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        outage_settings = replace(
            settings, base_url=f"http://127.0.0.1:{unavailable.getsockname()[1]}"
        )
        outage = ExportWorker(repo, OtlpTransport(outage_settings), random_fraction=lambda: 0)
        await outage.drain(limit=1)
    job = await repo.get(ingress.request_id)
    assert job.state == "RETRY_WAIT" and job.last_code == "connect_failed"
    await asyncio.sleep(max(0, (job.next_attempt_at - datetime.now(UTC)).total_seconds()) + 0.05)
    # Fresh repository/transport objects read durable work; independent-process tests
    # additionally establish interpreter restart behavior.
    restarted = ExportRepository(Database(os.environ["PROXYLENS_EXPORTER_TEST_DSN"]), settings)

    async def corrupt_success(request):
        async with httpx.AsyncClient(trust_env=False, timeout=10) as upstream:
            response = await upstream.post(
                str(request.url), headers=request.headers, content=request.content
            )
            assert response.status_code == 200
        # Deliberately corrupt only the acknowledgement after real sink acceptance.
        return httpx.Response(200, content=b"{")

    fault = httpx.MockTransport(corrupt_success) if args.malformed_success else None
    await ExportWorker(restarted, OtlpTransport(settings, transport=fault)).drain(limit=1)
    job = await restarted.get(ingress.request_id)
    expected = "UNCERTAIN" if args.malformed_success else "ACCEPTED"
    assert job.state == expected, job.state
    auth = httpx.BasicAuth(
        args.public_key_file.read_text().strip(), args.secret_key_file.read_text().strip()
    )
    params = {
        "traceId": ingress.trace_id,
        "limit": 100,
        "fields": "core,basic,io,metadata,usage,model,metrics",
        "fromStartTime": (ingress.accepted_at - timedelta(seconds=1)).isoformat(),
        "toStartTime": (obs.ended_at + timedelta(seconds=1)).isoformat(),
    }
    async with httpx.AsyncClient(auth=auth, trust_env=False, timeout=10) as client:
        rows = []
        for _ in range(40):
            response = await client.get(
                settings.base_url + "/api/public/v2/observations", params=params
            )
            response.raise_for_status()
            rows = response.json()["data"]
            if rows:
                break
            await asyncio.sleep(1)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == ingress.generation_id and row["traceId"] == ingress.trace_id
        assert row["type"] == "GENERATION" and row.get("parentObservationId") is None
        assert row.get("input") is None and row.get("output") is None
        # v4.69.0 readback represents an omitted machine user as an empty string.
        assert row.get("userId") in (None, "") and row["sessionId"] == str(ingress.request_id)
        assert row["metadata"]["usage_state"] == "usage_unproven"
        assert row["metadata"]["application_id"] == "poc-app"
        assert row["metadata"]["keycloak_group_id"] == "poc-group"
        assert not row.get("usageDetails") and not row.get("costDetails")
        # Replay scan and late update never schedule a second immutable generation.
        await restarted.enqueue(obs)
        late = await restarted.finalize(
            replace(obs, resolved_model="late-model"), reason="gateway_only"
        )
        assert late.remote_snapshot_stale
        assert await ExportWorker(restarted, OtlpTransport(settings)).drain(limit=1) == 0
        response = await client.get(
            settings.base_url + "/api/public/v2/observations", params=params
        )
        response.raise_for_status()
        assert len(response.json()["data"]) == 1
    summary = {
        "checked_at": datetime.now(UTC).isoformat(),
        "langfuse_version": "4.69.0",
        "request_id": str(ingress.request_id),
        "trace_id": ingress.trace_id,
        "generation_id": ingress.generation_id,
        "outage_state": "RETRY_WAIT/connect_failed",
        "restarted_state": job.state,
        "delivery_code": job.last_code,
        "attempts": job.attempts,
        "visible_root_generations": 1,
        "input": None,
        "output": None,
        "usage_state": "usage_unproven",
        "provided_usage": False,
        "provided_cost": False,
        "late_enrichment_local_only": late.remote_snapshot_stale,
        "provider_requests": 0,
    }
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--public-key-file", type=Path, required=True)
    parser.add_argument("--secret-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--malformed-success", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
