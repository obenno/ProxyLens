"""Seed CPA's writable config volume. JSON is accepted by its YAML loader."""

import json
import os
from pathlib import Path


def _yaml_safety_values(text: str) -> dict[tuple[str, ...], str]:
    """Read only the scalar mapping paths required for the logging guard."""

    values: dict[tuple[str, ...], str] = {}
    parents: list[tuple[int, tuple[str, ...]]] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("-"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, separator, value = line.strip().partition(":")
        if not separator:
            continue
        key = key.strip().strip("'\"")
        if not key:
            continue
        while parents and indent <= parents[-1][0]:
            parents.pop()
        path = (parents[-1][1] if parents else ()) + (key,)
        value = value.strip()
        if value:
            values[path] = value.strip("'\"")
        else:
            parents.append((indent, path))
    return values


def _has_safe_logging_guard(target: Path) -> bool:
    """Return whether a persisted CPA config disables raw request capture."""

    text = target.read_text()
    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        values = _yaml_safety_values(text)
        return all(
            values.get(path) == expected
            for path, expected in (
                (("server", "commercial-mode"), "true"),
                (("observability", "logs", "debug"), "false"),
                (("observability", "logs", "logging-to-file"), "false"),
                (("observability", "logs", "request-log"), "false"),
            )
        )
    logs = config.get("observability", {}).get("logs", {})
    return (
        config.get("server", {}).get("commercial-mode") is True
        and logs.get("debug") is False
        and logs.get("logging-to-file") is False
        and logs.get("request-log") is False
    )


directory = Path(os.environ.get("CPA_CONFIG_DIR", "/config"))
target = directory / "config.yaml"
if target.exists():
    if not _has_safe_logging_guard(target):
        raise SystemExit(
            "Existing CLIProxyAPI config lacks the required raw-logging safety guard; "
            "migrate it before starting CPA"
        )
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
