"""Project-owned secret-file launcher contract; no upstream feature tests."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "deploy/candidate/secret_env.py"


def test_secret_launcher_loads_files_without_shell_expansion(tmp_path):
    values = {
        "LITELLM_MASTER_KEY": "sk-fixture-$(not-a-command)",
        "LITELLM_SALT_KEY": "fixture-salt",
        "UI_PASSWORD": "fixture-ui",
        "CPA_API_KEY": "fixture-cpa",
        "POSTGRES_PASSWORD": "p@ss/word",
        "LANGFUSE_SECRET_KEY": "fixture-callback",
    }
    env = os.environ.copy()
    for name, value in values.items():
        path = tmp_path / name
        path.write_text(value + "\n")
        env[name + "_FILE"] = str(path)
    result = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER),
            sys.executable,
            "-c",
            "import os,json; print(json.dumps({k:os.environ[k] for k in "
            + repr([*values, "DATABASE_URL"])
            + "}))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        **values,
        "DATABASE_URL": "postgresql://litellm:p%40ss%2Fword@postgres:5432/litellm",
    }


def test_healthcheck_is_shell_quoted_for_podman_compose():
    config = yaml.safe_load((ROOT / "deploy/candidate/compose.yaml").read_text())
    check = config["services"]["litellm"]["healthcheck"]["test"]
    assert check[0] == "CMD-SHELL"
    # The API's argv healthchecks lose quotes under Podman; the shell form must
    # preserve Python's -c argument as one item.
    args = shlex.split(check[1])
    assert args[:2] == ["python", "-c"]
    assert len(args) == 3
    compile(args[2], "healthcheck", "exec")


def test_init_creates_private_secrets_and_refuses_to_rotate_existing_state(tmp_path):
    upstream = tmp_path / "authorized-cpa-key"
    upstream.write_text("sk-synthetic-cpa\n")
    upstream.chmod(0o600)
    private = tmp_path / "candidate"
    command = [
        sys.executable,
        str(ROOT / "scripts/candidate.py"),
        "init",
        "--private-dir",
        str(private),
        "--cpa-key-file",
        str(upstream),
        "--cpa-network",
        "authorized-test",
        "--cpa-base",
        "http://cpa:8317/v1",
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert private.stat().st_mode & 0o777 == 0o700
    secret = private / "secrets/master_key"
    initial = secret.read_text()
    assert initial.startswith("sk-")
    assert secret.stat().st_mode & 0o777 == 0o600
    assert (private / "secrets/cpa_api_key").read_text() == upstream.read_text()
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode != 0
    assert secret.read_text() == initial
    assert "sk-synthetic-cpa" not in first.stdout + first.stderr + second.stdout + second.stderr


def test_missing_secret_aborts_before_launch_and_does_not_disclose_values(tmp_path):
    env = os.environ.copy()
    env["POSTGRES_PASSWORD_FILE"] = str(tmp_path / "absent")
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), sys.executable, "-c", "print('LAUNCHED')"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "LAUNCHED" not in result.stdout
    assert "cannot load POSTGRES_PASSWORD_FILE" in result.stderr
