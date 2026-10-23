"""Seed CPA's writable config volume. JSON is accepted by its YAML loader."""

import json
import os
from pathlib import Path

directory = Path(os.environ.get("CPA_CONFIG_DIR", "/config"))
target = directory / "config.yaml"
if target.exists():
    print("Existing CLIProxyAPI config preserved.")
else:
    secrets = Path(os.environ.get("SECRETS_DIR", "/run/secrets"))
    config = json.loads(Path(os.environ.get("CPA_TEMPLATE", "/bootstrap/config.json")).read_text())
    management_key = (secrets / "cpa_management_key").read_text().strip()
    client_key = (secrets / "cpa_client_key").read_text().strip()
    if not management_key or not client_key:
        raise SystemExit("CLIProxyAPI requires nonempty mounted management and client keys")
    config["management"]["secret-key"] = management_key
    config["access"]["api-keys"] = [client_key]
    # Only one initializer runs. Atomic publish prevents a partial config on interruption.
    temporary = directory / ".config.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(config, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(target)
    print("CLIProxyAPI config initialized.")
