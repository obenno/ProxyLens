import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_is_repeatable_and_preserves_existing_secrets_and_cpa_config(tmp_path):
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
    assert config["observability"]["logs"]["request-log"] is False
    assert original["cpa_management_key"].strip() not in result.stdout + result.stderr
    # An operator may change settings through CPA, which rewrites this as YAML.
    (config_dir / "config.yaml").write_text("config-version: 8\n# operator change\n")
    subprocess.run(command, env=env, check=True, capture_output=True)
    assert (config_dir / "config.yaml").read_text() == "config-version: 8\n# operator change\n"


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
