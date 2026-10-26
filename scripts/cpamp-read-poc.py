#!/usr/bin/env python3
"""Exercise the production adapter against an isolated official v1.14.9 binary.

Only this harness imports/archives its synthetic scratch data. The adapter is read-only.
Run with PYTHONPATH=src and --release-archive downloaded from the pinned release.
"""

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import tarfile
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from proxylens.cpamp import CPAMPAdapter, HistoryWindow

RELEASE_SHA256 = "d3d2d4977bbfded997656d3a65fe8f405890312c2e4a595359c5af675f029455"
SOURCE_SHA = "6d962db680085827cd19a778d2ff05a3d1315672"
FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/cpamp-v1.14.9/export.jsonl"


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


async def ready(client, process):
    for _ in range(200):
        if process.poll() is not None:
            raise RuntimeError("isolated CPAMP exited before readiness")
        try:
            response = await client.get("/status")
            if response.status_code == 200:
                collector = response.json()["collector"]
                assert collector["collector"] == "stopped"
                assert collector["upstream"] == ""
                assert collector["totalInserted"] == collector["lastConsumedAt"] == 0
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.05)
    raise RuntimeError("isolated CPAMP readiness timeout")


async def exercise(binary, scratch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    key = secrets.token_urlsafe(32)
    config = scratch / "config.json"
    config.write_text("{}\n")
    env = {
        "PATH": os.defpath,
        "HOME": str(scratch),
        "CPA_MANAGER_CONFIG": str(config),
        "HTTP_ADDR": f"127.0.0.1:{port}",
        "USAGE_DATA_DIR": str(scratch / "data"),
        "CPA_MANAGER_ADMIN_KEY": key,
        "CPA_UPSTREAM_URL": "",
        "CPA_MANAGEMENT_KEY": "",
        "USAGE_QUERY_LIMIT": "2",
        "USAGE_ARCHIVE_RETENTION_ENABLED": "false",
    }
    # All timestamps are synthetic and in the past even on hosts with an earlier local date.
    stamp = int(time.time() * 1000) - 2 * 86_400_000
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines()]
    for row in rows:
        row["timestamp_ms"] = stamp
        row["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp / 1000))
        row.pop("created_at_ms", None)
    seed = "".join(json.dumps(row) + "\n" for row in rows)
    window = HistoryWindow(stamp, stamp + 1, providers=("codex",), models=("model-demo",))
    result = {
        "version": "v1.14.9",
        "source_sha": SOURCE_SHA,
        "release_archive_sha256": RELEASE_SHA256,
        "evidence": "released-binary synthetic HTTP; no CPA/provider configured",
        "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    log = (scratch / "server.log").open("wb")
    process = subprocess.Popen([str(binary)], cwd=scratch, env=env, stdout=log, stderr=log)
    try:
        async with httpx.AsyncClient(
            base_url=origin,
            headers={"Authorization": f"Bearer {key}"},
            trust_env=False,
            timeout=20,
        ) as setup:
            await ready(setup, process)
            imported = await setup.post("/v0/management/usage/import", content=seed)
            imported.raise_for_status()
            assert imported.json()["added"] == 3
            result["import"] = {k: imported.json()[k] for k in ("added", "skipped", "failed")}
            async with CPAMPAdapter(
                origin, key, instance_id="synthetic-poc", page_size=1
            ) as adapter:
                history = await adapter.read_window(window)
                assert history.state == "available", asdict(history)
                assert len(history.records) == history.pages == 3
                assert all(r.normalized.total_tokens == 140 for r in history.records)
                assert len({r.request_id for r in history.records}) == 2
                result["analytics"] = asdict(history)
                success = await adapter.read_window(
                    HistoryWindow(
                        stamp,
                        stamp + 1,
                        include_failed=False,
                    )
                )
                assert len(success.records) == 2
                excluded = await adapter.read_window(HistoryWindow(stamp - 1, stamp))
                assert excluded.state == "available" and not excluded.records
                wrong_provider = await adapter.read_window(
                    HistoryWindow(
                        stamp,
                        stamp + 1,
                        providers=("not-codex",),
                    )
                )
                assert not wrong_provider.records and wrong_provider.state == "available"
                searched = await adapter.read_window(
                    HistoryWindow(
                        stamp,
                        stamp + 1,
                        request_id=rows[0]["request_id"],
                    )
                )
                assert len(searched.records) == 2
                result["filter_counts"] = {
                    "success_only": 2,
                    "exclusive_upper_bound": 0,
                    "other_provider": 0,
                    "exact_request_id_attempts": 2,
                }
                exported = await adapter.read_export()
                assert exported.traversal_complete and len(exported.records) == 3
                assert not exported.snapshot_verified
                assert {r.identity for r in history.records} == {
                    r.identity for r in exported.records
                }
                assert all(r.raw_tokens["cached_tokens"] == 20 for r in exported.records)
                assert all(r.raw_tokens["cached_tokens"] == 0 for r in history.records)
                result["export"] = asdict(exported)
                result["collector"] = asdict(await adapter.read_status())
                duplicate = await setup.post("/v0/management/usage/import", content=seed)
                duplicate.raise_for_status()
                assert duplicate.json()["added"] == 0 and duplicate.json()["skipped"] == 3
                result["duplicate_import"] = {"added": 0, "skipped": 3}
                stop(process)
                outage = await adapter.read_window(window)
                assert outage.state == "unavailable" and adapter.last_success is not None
                result["outage"] = {"state": outage.state, "reasons": outage.reasons}
                process = subprocess.Popen(
                    [str(binary)],
                    cwd=scratch,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                await ready(setup, process)
                persisted = await adapter.read_window(window)
                assert persisted.records == history.records
                result["restart_persistence"] = "same 3 source identities and values"
                # Exercise real raw-history retention on this newly created scratch DB only.
                archive = await setup.post(
                    "/v0/management/usage/archives",
                    json={
                        "cutoff_timestamp_ms": stamp + 1,
                    },
                )
                archive.raise_for_status()
                archive_id = archive.json()["run"]["id"]
                stages = []
                for action in ("resume", "verify", "delete"):
                    response = await setup.post(
                        f"/v0/management/usage/archives/{archive_id}/{action}"
                    )
                    response.raise_for_status()
                    stages.append(response.json()["run"]["status"])
                retained = await adapter.read_window(window)
                assert retained.state == "degraded" and "retention_gap" in retained.reasons
                assert not retained.records
                result["retention"] = {"stages": stages, "read": asdict(retained)}
                after = await adapter.read_export()
                assert (
                    after.traversal_complete and not after.records and not after.snapshot_verified
                )
                result["export_after_retention"] = {"records": 0, "snapshot_verified": False}
            async with CPAMPAdapter(origin, "incorrect-key", instance_id="synthetic-poc") as bad:
                denied = await bad.read_window(window)
                assert denied.state == "unavailable" and "authentication" in denied.reasons
                result["auth"] = {"state": denied.state, "reasons": denied.reasons}
            await ready(setup, process)
    finally:
        stop(process)
        log.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=Path(
            "/data/tmp/opencode" if Path("/data/tmp/opencode").is_dir() else tempfile.gettempdir()
        ),
    )
    args = parser.parse_args()
    if hashlib.sha256(args.release_archive.read_bytes()).hexdigest() != RELEASE_SHA256:
        raise SystemExit(
            "release archive checksum mismatch (expected official Linux amd64 v1.14.9)"
        )
    with tempfile.TemporaryDirectory(
        prefix="cpamp-adapter-poc-", dir=args.scratch_root
    ) as directory:
        scratch = Path(directory)
        with tarfile.open(args.release_archive) as archive:
            archive.extractall(scratch / "release", filter="data")
        binary = next((scratch / "release").glob("*/cpa-manager-plus"))
        version = subprocess.check_output([str(binary), "--version"], text=True).strip()
        assert version == "v1.14.9"
        result = asyncio.run(exercise(binary, scratch))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": "passed", "version": version, "output": str(args.output)}))


if __name__ == "__main__":
    main()
