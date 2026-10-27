#!/usr/bin/env python3
"""Explicit tiny provider checks; private manifest/results, aggregate-only stdout.

This harness never enables proof gates, imports usage, or consumes the CPA queue.
See docs/live-acceptance.md for setup, ownership and evidence limits.
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import stat
import struct
import sys
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx

CASES = ("nonstream", "stream", "tool", "image", "cancellation", "worker-outage")
MAX_BYTES = 131072


def private_text(path):
    path = Path(path)
    mode = path.lstat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.getuid() or mode.st_mode & 0o077:
        raise ValueError("private_file_required")
    return path.read_text().strip()


def write_private(path, value):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def milliseconds():
    return time.time_ns() // 1_000_000


def reserve_dispatch(directory, case):
    """Commit an exclusive reservation before dispatch; unknown outcomes are not retried."""
    path = directory / f"{case}.reserved"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            {"state": "reserved_outcome_unknown", "reserved_ms": time.time_ns() // 10**6}, stream
        )
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class HistoryTransport(httpx.AsyncBaseTransport):
    """An independent HTTP boundary excludes queue/management writes from this harness."""

    def __init__(self, base_url):
        from proxylens.cpamp import ANALYTICS_PATH

        self.origin = httpx.URL(base_url)
        self.analytics_path = ANALYTICS_PATH
        self.inner = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        if (request.url.scheme, request.url.host, request.url.port) != (
            self.origin.scheme,
            self.origin.host,
            self.origin.port,
        ) or (request.method, request.url.path) not in {
            ("POST", self.analytics_path),
            ("GET", "/status"),
        }:
            raise ValueError("history_read_only")
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


def synthetic_image():
    def chunk(kind, body):
        return (
            struct.pack("!I", len(body)) + kind + body + struct.pack("!I", zlib.crc32(kind + body))
        )

    raw = b"\x89PNG\r\n\x1a\n"
    raw += chunk(b"IHDR", struct.pack("!2I5B", 32, 32, 8, 2, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress((b"\0" + b"\xff\0\0" * 32) * 32))
    raw += chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def payload(model, case):
    value = {
        "model": model,
        "store": False,
        "max_output_tokens": 32,
        "reasoning": {"effort": "low"},
        "instructions": "Synthetic compatibility check. Be brief.",
        "input": "Reply exactly OK.",
        "stream": case in {"stream", "tool", "cancellation"},
    }
    if case == "tool":
        value.update(
            {
                "input": "Call synthetic_echo once with value 1. No prose.",
                "parallel_tool_calls": False,
                "tools": [
                    {
                        "type": "function",
                        "name": "synthetic_echo",
                        "description": "Echo a synthetic value.",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "integer"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "strict": True,
                    }
                ],
                "tool_choice": {"type": "function", "name": "synthetic_echo"},
            }
        )
    elif case == "image":
        value["input"] = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Name the solid color. One word only."},
                    {"type": "input_image", "image_url": synthetic_image(), "detail": "low"},
                ],
            }
        ]
    return value


def response_checks(response, case):
    outputs = response.get("output", [])
    text = (
        "".join(
            part.get("text", "")
            for item in outputs
            for part in item.get("content", [])
            if part.get("type") == "output_text"
        )
        .strip()
        .rstrip(".")
        .lower()
    )
    calls = [item for item in outputs if item.get("type") == "function_call"]
    expected = (
        (
            len(calls) == 1
            and calls[0].get("name") == "synthetic_echo"
            and json.loads(calls[0]["arguments"]) == {"value": 1}
        )
        if case == "tool"
        else text == ("red" if case == "image" else "ok")
    )
    return {
        "response_completed": response.get("status") == "completed",
        "expected_result": expected,
    }


async def dispatch(manifest, directory, case):
    # Prior incomplete dispatch prevents running the remaining cases after an auth/quota failure.
    for reservation in directory.glob("*.reserved"):
        result = directory / (reservation.stem + ".json")
        if not result.exists() or not json.loads(private_text(result)).get("continue_allowed"):
            raise ValueError("prior_outcome_requires_review")
    group = "beta" if case in {"stream", "image", "worker-outage"} else "alpha"
    owner = manifest["applications"][group]
    if case == "worker-outage":
        try:
            response = httpx.get(
                manifest["worker_url"] + "/health/ready", timeout=8, trust_env=False
            )
            worker_status = response.status_code
        except httpx.HTTPError:
            worker_status = "unreachable"
        if worker_status == 200:
            raise ValueError("worker_must_be_stopped_for_outage_case")
        reserve_dispatch(directory, case)
        result = {
            "case": case,
            "worker_ready_status": worker_status,
            "provider_requests": 0,
            "continue_allowed": True,
        }
        write_private(directory / f"{case}.json", result)
        return result
    body = payload(manifest["model"], case)
    key = private_text(owner["key_file"])
    item = {"case": case, "group": group, "started_ms": milliseconds(), "continue_allowed": False}
    reserve_dispatch(directory, case)
    write_private(directory / f"{case}.json", item)
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=45) as client:
        async with asyncio.timeout(50):
            async with client.stream(
                "POST",
                manifest["gateway_url"] + "/v1/responses",
                json=body,
                headers={"Authorization": "Bearer " + key, "Accept-Encoding": "identity"},
            ) as response:
                item["http_status"] = response.status_code
                item["request_id"] = str(UUID(response.headers["x-request-id"]))
                native = UUID(response.headers["x-cpa-request-id"])
                assert native.version == 7
                item["cpa_request_id"] = str(native)
                item["headers_ms"] = milliseconds()
                write_private(directory / f"{case}.json", item)
                if response.status_code != 200:
                    raise ValueError("upstream_rejected_stop")
                consumed = bytearray()
                terminal = None
                events = 0
                async for chunk in response.aiter_bytes():
                    item.setdefault("first_byte_ms", milliseconds())
                    consumed.extend(chunk)
                    if len(consumed) > MAX_BYTES:
                        raise ValueError("response_limit")
                    if body["stream"]:
                        lines = bytes(consumed).split(b"\n")
                        consumed = bytearray(lines.pop())
                        for line in lines:
                            if not line.startswith(b"data:") or line[5:].strip() == b"[DONE]":
                                continue
                            value = json.loads(line[5:])
                            events += 1
                            kind = value.get("type")
                            if kind in {"error", "response.failed"}:
                                raise ValueError("provider_error_stop")
                            if kind == "response.completed":
                                terminal = value["response"]
                            if case == "cancellation" and kind == "response.created":
                                item["cancelled_after_created"] = True
                                break
                        if item.get("cancelled_after_created"):
                            break
                if case not in {"cancellation", "worker-outage"}:
                    terminal = terminal if body["stream"] else json.loads(consumed)
                    item.update(response_checks(terminal, case))
                    item["response_usage"] = {
                        k: v
                        for k, v in terminal.get("usage", {}).items()
                        if k in {"input_tokens", "output_tokens", "total_tokens"} and type(v) is int
                    }
                    item["stream_event_count"] = events
                    assert item["response_completed"] and item["expected_result"]
    item["finished_ms"] = milliseconds()
    write_private(directory / f"{case}.json", item)
    await read_history(manifest, item)
    await lineage_checks(manifest, item)
    item["continue_allowed"] = case == "cancellation" or item.get("exact_durable_join", False)
    write_private(directory / f"{case}.json", item)
    return public_result(item)


async def read_history(manifest, item):
    from proxylens.cpamp import CPAMPAdapter, HistoryWindow

    async with CPAMPAdapter(
        manifest["cpamp_url"],
        private_text(manifest["cpamp_key_file"]),
        instance_id=manifest["cpamp_instance_id"],
        page_size=1,
        max_pages=30,
        transport=HistoryTransport(manifest["cpamp_url"]),
    ) as adapter:
        deadline = time.monotonic() + 65
        while True:
            result = await adapter.read_window(
                HistoryWindow(
                    item["started_ms"] - 1000,
                    item["finished_ms"] + 1000,
                    request_id=item["cpa_request_id"],
                )
            )
            matched = [r for r in result.records if r.request_id == item["cpa_request_id"]]
            if matched or time.monotonic() >= deadline or result.state == "unavailable":
                break
            await asyncio.sleep(1)
        item["history_state"] = result.state
        item["durable_records"] = len(matched)
        item["event_hashes"] = [r.event_hash for r in matched]
        item["exact_durable_join"] = len(matched) == 1 and result.traversal_complete
        item["cpamp_visibility_ms"] = milliseconds() - item["finished_ms"] if matched else None
        item["normalized_usage_known"] = bool(matched) and all(
            r.normalized.buckets for r in matched
        )
        item["normalization_matches_response_total"] = bool(matched) and all(
            r.normalized.total_tokens == item.get("response_usage", {}).get("total_tokens")
            for r in matched
        )
        item["route_matches_attestation"] = bool(matched) and all(
            r.provider == "codex" and r.resolved_model == manifest["model"] for r in matched
        )
        # Duplicate HTTP reads must preserve the exact event identities.
        again = await adapter.read_window(
            HistoryWindow(
                item["started_ms"] - 1000,
                item["finished_ms"] + 1000,
                request_id=item["cpa_request_id"],
            )
        )
        item["repeat_read_same_hashes"] = item["event_hashes"] == [
            r.event_hash for r in again.records
        ]


async def lineage_checks(manifest, item):
    from proxylens.config import Settings
    from proxylens.lineage import LineageRepository

    os.environ.update(json.loads(private_text(manifest["environment_file"])))
    settings = Settings.from_environment()
    assert not settings.proof_gate().enabled
    async with settings.database().transaction() as conn:
        ingress = await LineageRepository(conn).get_ingress(UUID(item["request_id"]))
        owner = manifest["applications"][item["group"]]
        assert ingress is not None
        item["ownership_exact"] = (
            ingress.owner.application_id == owner["application_id"]
            and ingress.owner.keycloak_group_id == owner["group_id"]
            and ingress.owner.client_key_id == owner["key_id"]
        )
        assert item["ownership_exact"]
        item["trace_id"] = ingress.trace_id
        item["generation_id"] = ingress.generation_id
        # Documented exporter view is the durable gateway lifecycle seam.
        row = await (
            await conn.execute(
                "SELECT outcome, first_byte_at, completed_at FROM "
                "gateway_observations WHERE request_id=%s",
                (ingress.request_id,),
            )
        ).fetchone()
        item["gateway_outcome"] = row["outcome"]
        item["first_byte_before_completion"] = bool(
            row["first_byte_at"]
            and row["completed_at"]
            and row["first_byte_at"] < row["completed_at"]
        )
        binding = await (
            await conn.execute(
                "SELECT request_id FROM lineage_native_binding "
                "WHERE cpa_instance_id=%s AND cpa_request_id=%s",
                (manifest["cpa_instance_id"], UUID(item["cpa_request_id"])),
            )
        ).fetchall()
        item["unique_native_binding"] = (
            len(binding) == 1 and binding[0]["request_id"] == ingress.request_id
        )


async def readback(manifest, directory):
    auth = httpx.BasicAuth(
        private_text(manifest["langfuse_public_key_file"]),
        private_text(manifest["langfuse_secret_key_file"]),
    )
    results = []
    async with httpx.AsyncClient(
        auth=auth, timeout=10, trust_env=False, follow_redirects=False
    ) as client:
        for case in CASES:
            path = directory / f"{case}.json"
            if not path.exists():
                continue
            item = json.loads(private_text(path))
            if "trace_id" not in item:
                continue
            params = {
                "traceId": item["trace_id"],
                "limit": 100,
                "fields": "core,basic,io,metadata,usage,model,metrics",
                "fromStartTime": (
                    datetime.fromtimestamp(item["started_ms"] / 1000, UTC) - timedelta(seconds=1)
                ).isoformat(),
                "toStartTime": (
                    datetime.fromtimestamp(item["finished_ms"] / 1000, UTC) + timedelta(seconds=2)
                ).isoformat(),
            }
            rows = []
            for _ in range(45):
                response = await client.get(
                    manifest["langfuse_url"] + "/api/public/v2/observations", params=params
                )
                response.raise_for_status()
                rows = response.json()["data"]
                if rows:
                    break
                await asyncio.sleep(1)
            assert len(rows) == 1
            row = rows[0]
            metadata = row["metadata"]
            owner = manifest["applications"][item["group"]]
            assert row["id"] == item["generation_id"] and row["type"] == "GENERATION"
            assert row.get("input") is None and row.get("output") is None
            assert row.get("userId") in (None, "") and row["sessionId"] == item["request_id"]
            assert metadata["application_id"] == owner["application_id"]
            assert metadata["keycloak_group_id"] == owner["group_id"]
            assert metadata["cpa_request_id"] == item["cpa_request_id"]
            assert metadata["usage_state"] == "usage_unproven"
            assert metadata["correlation_status"] == "partial"
            assert "cpamp_event_hash" not in metadata
            assert not row.get("usageDetails") and not row.get("costDetails")
            results.append(
                {
                    "case": case,
                    "single_generation": True,
                    "ownership_and_native_id": True,
                    "no_content_or_fabricated_usage": True,
                    "machine_identity": True,
                }
            )
    write_private(directory / "langfuse-readback.json", results)
    return {"langfuse_verified_generations": len(results), "tenant_gate_enabled": False}


def public_result(item):
    return {
        key: item.get(key)
        for key in (
            "case",
            "http_status",
            "response_completed",
            "expected_result",
            "durable_records",
            "exact_durable_join",
            "cpamp_visibility_ms",
            "normalization_matches_response_total",
            "route_matches_attestation",
            "ownership_exact",
            "unique_native_binding",
            "gateway_outcome",
            "first_byte_before_completion",
            "continue_allowed",
        )
    }


def main():
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--directory", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    send = commands.add_parser("dispatch")
    send.add_argument("--case", choices=CASES, required=True)
    commands.add_parser("readback")
    args = parser.parse_args()
    try:
        manifest = json.loads(private_text(args.manifest))
        args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if args.directory.stat().st_mode & 0o077:
            raise ValueError("private_directory_required")
        result = asyncio.run(
            dispatch(manifest, args.directory, args.case)
            if args.command == "dispatch"
            else readback(manifest, args.directory)
        )
        print(json.dumps(result))
        return 0
    except Exception:
        # Never print traceback, provider bodies, URL queries or exception text.
        print(json.dumps({"status": "blocked", "reason": "local_check_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
