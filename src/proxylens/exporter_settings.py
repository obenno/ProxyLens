"""Exporter-only settings. The application/worker owner wires these explicitly."""

import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from proxylens.exporter import ExportError


@dataclass(frozen=True)
class ExporterSettings:
    enabled: bool = False
    destination: str = "langfuse"
    base_url: str = "http://langfuse-web:3000"
    public_key_file: Path = Path("/run/secrets/langfuse_public_key")
    secret_key_file: Path = Path("/run/secrets/langfuse_secret_key")
    max_payload_bytes: int = 32768
    max_response_bytes: int = 65536
    max_spool_rows: int = 100000
    max_spool_bytes: int = 256 * 1024 * 1024
    max_attempts: int = 10
    max_age_seconds: int = 86400
    usage_wait_seconds: int = 300
    retention_seconds: int = 90 * 86400
    lease_seconds: int = 60
    request_timeout_seconds: float = 10
    backoff_base_seconds: float = 1
    backoff_cap_seconds: float = 300
    # Enable only with operator evidence that this destination's 429 is pre-admission.
    trusted_pre_admission_429: bool = False
    # A destination may attest that a temporary HTTP response happened before
    # admission. Without this destination-specific signal, the response is
    # ambiguous because a proxy may fail after Langfuse accepted the payload.
    trusted_pre_admission_temporary_failures: bool = False

    def __post_init__(self):
        from proxylens.exporter import _safe

        _safe(self.destination)
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ExportError("invalid_exporter_url")
        for name in (
            "max_payload_bytes",
            "max_response_bytes",
            "max_spool_rows",
            "max_spool_bytes",
            "max_attempts",
            "max_age_seconds",
            "usage_wait_seconds",
            "retention_seconds",
            "lease_seconds",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ExportError("invalid_exporter_limit")
        for name in ("request_timeout_seconds", "backoff_base_seconds", "backoff_cap_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ExportError("invalid_exporter_limit")
        if (
            self.request_timeout_seconds >= self.lease_seconds
            or self.retention_seconds < self.max_age_seconds
            or self.backoff_base_seconds > self.backoff_cap_seconds
        ):
            raise ExportError("invalid_exporter_limit")

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/api/public/otel/v1/traces"
