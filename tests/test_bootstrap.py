import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_is_repeatable_and_preserves_existing_secrets_and_cpa_config(tmp_path):
    template = json.loads((ROOT / "deploy/cliproxyapi/config.json").read_text())
    assert template["server"]["commercial-mode"] is True
    assert template["observability"]["logs"] == {
        "debug": False,
        "logging-to-file": False,
        "request-log": False,
    }
    secret_dir = tmp_path / "secrets"
    command = [sys.executable, str(ROOT / "scripts/init-secrets.py"), str(secret_dir)]
    subprocess.run(command, check=True, capture_output=True)
    original = {path.name: path.read_bytes() for path in secret_dir.iterdir()}
    subprocess.run(command, check=True, capture_output=True)
    assert original == {path.name: path.read_bytes() for path in secret_dir.iterdir()}
    assert len(base64.b64decode(original["cpamp_data_key"])) == 32
    assert original["langfuse_secret_key"] == b""
    assert secret_dir.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o644 for path in secret_dir.iterdir())

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    env = {
        **os.environ,
        "SECRETS_DIR": str(secret_dir),
        "CPA_CONFIG_DIR": str(config_dir),
        "CPA_TEMPLATE": str(ROOT / "deploy/cliproxyapi/config.json"),
    }
    command = [sys.executable, str(ROOT / "deploy/cliproxyapi/init.py")]
    result = subprocess.run(command, env=env, check=True, capture_output=True)
    config = json.loads((config_dir / "config.yaml").read_text())
    assert config["management"]["secret-key"] == original["cpa_management_key"].decode().strip()
    assert config["access"]["api-keys"] == [original["cpa_client_key"].decode().strip()]
    assert config["server"]["commercial-mode"] is True
    assert config["observability"]["logs"] == {
        "debug": False,
        "logging-to-file": False,
        "request-log": False,
    }
    assert config["observability"]["logs"]["request-log"] is False
    assert original["cpa_management_key"].strip() not in result.stdout + result.stderr
    # An operator may change settings through CPA, which rewrites this as YAML.
    safe_existing = """config-version: 8
server:
  host: 0.0.0.0
  port: 8317
  commercial-mode: true
observability:
  logs:
    debug: false
    logging-to-file: false
    request-log: false
# operator change
"""
    (config_dir / "config.yaml").write_text(safe_existing)
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert (config_dir / "config.yaml").read_text() == safe_existing


def test_cpa_initialization_rejects_existing_config_without_raw_logging_guard(tmp_path):
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "cpa_management_key").write_text("management-key\n")
    (secret_dir / "cpa_client_key").write_text("client-key\n")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    unsafe_existing = """config-version: 8
server:
  host: 0.0.0.0
  port: 8317
observability:
  logs:
    request-log: false
"""
    target = config_dir / "config.yaml"
    target.write_text(unsafe_existing)
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/cliproxyapi/init.py")],
        env={
            **os.environ,
            "SECRETS_DIR": str(secret_dir),
            "CPA_CONFIG_DIR": str(config_dir),
            "CPA_TEMPLATE": str(ROOT / "deploy/cliproxyapi/config.json"),
        },
        capture_output=True,
    )
    assert result.returncode != 0
    assert target.read_text() == unsafe_existing
    assert b"management-key" not in result.stdout + result.stderr
    assert b"client-key" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "server",
    [
        "  commercial-mode: false\n  notes: |\n    commercial-mode: true\n",
        '  commercial-mode: "true"\n',
        "  commercial-mode: false\n  commercial-mode: true\n",
        '  notes: "multiline\n  commercial-mode: true\n  ignored: end"\n',
        "  commercial-mode: true\nserver: {}\n",
    ],
    ids=["block-scalar", "quoted-boolean", "duplicate", "multiline-quote", "shadowed-parent"],
)
def test_cpa_initialization_rejects_ambiguous_logging_guard(tmp_path, server):
    existing = (
        """config-version: 8
"""
        + server
        + """\
observability:
  logs:
    debug: false
    logging-to-file: false
    request-log: false
management:
  secret-key: synthetic-persisted-secret
"""
    )
    target = tmp_path / "config.yaml"
    target.write_text(existing)
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "deploy/cliproxyapi/init.py")],
        env={**os.environ, "CPA_CONFIG_DIR": str(tmp_path)},
        capture_output=True,
    )
    assert result.returncode != 0
    assert target.read_text() == existing
    assert b"synthetic-persisted-secret" not in result.stdout + result.stderr


def test_cpa_initialization_rejects_duplicate_json_guard_without_echoing_config(tmp_path):
    existing = """{"server":{"commercial-mode":false,"commercial-mode":true},
"observability":{"logs":{"debug":false,"logging-to-file":false,"request-log":false}},
"management":{"secret-key":"synthetic-persisted-secret"}}"""
    target = tmp_path / "config.yaml"
    target.write_text(existing)
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "deploy/cliproxyapi/init.py")],
        env={**os.environ, "CPA_CONFIG_DIR": str(tmp_path)},
        capture_output=True,
    )
    assert result.returncode != 0
    assert target.read_text() == existing
    assert b"synthetic-persisted-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("value", [None, "\n"])
def test_cpa_initialization_fails_closed_without_a_management_key(tmp_path, value):
    if value is not None:
        (tmp_path / "cpa_management_key").write_text(value)
    (tmp_path / "cpa_client_key").write_text("test-client-key")
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/cliproxyapi/init.py")],
        env={
            **os.environ,
            "SECRETS_DIR": str(tmp_path),
            "CPA_CONFIG_DIR": str(tmp_path),
            "CPA_TEMPLATE": str(ROOT / "deploy/cliproxyapi/config.json"),
        },
        capture_output=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "config.yaml").exists()
    assert b"test-client-key" not in result.stdout + result.stderr
