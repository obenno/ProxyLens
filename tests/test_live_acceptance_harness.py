"""Acceptance CLI safety seam: a reserved provider scenario cannot be dispatched twice."""

import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def harness():
    path = Path(__file__).parents[1] / "scripts/live-acceptance.py"
    spec = importlib.util.spec_from_file_location("live_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dispatch_reservation_is_durable_exclusive_and_private(tmp_path):
    module = harness()

    def reserve(_):
        try:
            module.reserve_dispatch(tmp_path, "nonstream")
            return True
        except FileExistsError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(16))) == 1
    # A fresh process/module observes the reservation, even if no result was saved.
    try:
        harness().reserve_dispatch(tmp_path, "nonstream")
    except FileExistsError:
        pass
    else:
        raise AssertionError("reserved dispatch was replayable")
    path = tmp_path / "nonstream.reserved"
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["state"] == "reserved_outcome_unknown"


def test_cli_failure_does_not_print_private_manifest_or_exception(tmp_path):
    manifest = tmp_path / "private.json"
    manifest.write_text('{"secret": "synthetic-never-print-marker",')
    manifest.chmod(0o600)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/live-acceptance.py",
            "--manifest",
            str(manifest),
            "--directory",
            str(tmp_path),
            "dispatch",
            "--case",
            "nonstream",
        ],
        env={**__import__("os").environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "synthetic-never-print-marker" not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "blocked", "reason": "local_check_failed"}
