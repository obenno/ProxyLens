"""Nonsecret configuration and explicit file-based secret access."""

import os
from dataclasses import dataclass
from pathlib import Path

from proxylens.db import Database
from proxylens.exporter_settings import ExporterSettings
from proxylens.gateway import GatewaySettings
from proxylens.keycloak import IdentitySettings
from proxylens.operations import RetentionPolicy
from proxylens.projection_settings import (
    DISABLED_PROOF_GATE,
    ProjectionSettings,
    ProofGate,
    load_proof_gate,
)


def secret_file(variable: str, default: str) -> str:
    value = Path(os.environ.get(variable, default)).read_text().strip()
    if not value:
        raise ValueError(f"{variable} must reference a nonempty secret file")
    return value


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    keycloak_url: str
    cpa_url: str
    cpamp_url: str
    identity: IdentitySettings
    gateway: GatewaySettings = GatewaySettings()
    projection: ProjectionSettings = ProjectionSettings(
        cpamp_instance_id="primary",
        cpa_instance_id="primary",
        keycloak_issuer="http://localhost:8080/realms/proxylens",
    )
    exporter: ExporterSettings = ExporterSettings()
    retention: RetentionPolicy = RetentionPolicy()
    worker_interval_seconds: float = 5.0
    retention_interval_seconds: float = 3600.0
    group_reconcile_interval_seconds: float = 3600.0
    completion_pending_seconds: int = 300
    worker_scan_limit: int = 100
    worker_drain_limit: int = 100
    projection_proof_files: tuple[Path, ...] = ()
    projection_proof_digests: frozenset[str] = frozenset()

    def database(self) -> Database:
        return Database(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password_file=os.getenv("PROXYLENS_DB_PASSWORD_FILE", "/run/secrets/postgres_password"),
        )

    def proof_gate(self) -> ProofGate:
        if len(self.projection_proof_files) != 2 or len(self.projection_proof_digests) != 2:
            return DISABLED_PROOF_GATE
        return load_proof_gate(
            self.projection,
            self.projection_proof_files,
            approved_sha256=self.projection_proof_digests,
        )

    @classmethod
    def from_environment(cls) -> "Settings":
        issuer = os.getenv("PROXYLENS_KEYCLOAK_ISSUER", "http://localhost:8080/realms/proxylens")
        cpamp_instance_id = os.getenv("PROXYLENS_CPAMP_INSTANCE_ID", "primary")
        cpa_instance_id = os.getenv("PROXYLENS_CPA_INSTANCE_ID", "primary")
        langfuse_url = os.getenv("PROXYLENS_LANGFUSE_URL", "").strip()
        proof_files = tuple(
            Path(value)
            for value in (
                os.getenv("PROXYLENS_PROJECTION_CORRELATION_PROOF_FILE", ""),
                os.getenv("PROXYLENS_PROJECTION_HISTORY_PROOF_FILE", ""),
            )
            if value
        )
        proof_digests = frozenset(
            value.strip()
            for value in os.getenv("PROXYLENS_PROJECTION_APPROVED_DIGESTS", "").split(",")
            if value.strip()
        )
        return cls(
            db_host=os.getenv("PROXYLENS_DB_HOST", "postgres"),
            db_port=int(os.getenv("PROXYLENS_DB_PORT", "5432")),
            db_name=os.getenv("PROXYLENS_DB_NAME", "proxylens"),
            db_user=os.getenv("PROXYLENS_DB_USER", "proxylens"),
            keycloak_url=os.getenv("PROXYLENS_KEYCLOAK_URL", "http://keycloak:8080").rstrip("/"),
            cpa_url=os.getenv("PROXYLENS_CPA_URL", "http://cliproxyapi:8317").rstrip("/"),
            cpamp_url=os.getenv("PROXYLENS_CPAMP_URL", "http://cpamp:18317").rstrip("/"),
            gateway=GatewaySettings(
                registry_file=os.getenv("PROXYLENS_ROUTING_REGISTRY", "deploy/gateway/routes.json"),
                credential_file=os.getenv(
                    "PROXYLENS_CPA_CLIENT_KEY_FILE", "/run/secrets/cpa_client_key"
                ),
                cpa_instance_id=os.getenv("PROXYLENS_CPA_INSTANCE_ID", "primary"),
                max_body_bytes=int(os.getenv("PROXYLENS_MAX_BODY_BYTES", "4194304")),
                total_timeout=float(os.getenv("PROXYLENS_TOTAL_TIMEOUT", "120")),
                idle_timeout=float(os.getenv("PROXYLENS_IDLE_TIMEOUT", "30")),
            ),
            identity=IdentitySettings(
                issuer=issuer,
                internal_url=os.getenv("PROXYLENS_KEYCLOAK_URL", "http://keycloak:8080").rstrip(
                    "/"
                ),
                admin_secret_file=os.getenv(
                    "PROXYLENS_KEYCLOAK_CLIENT_SECRET_FILE", "/run/secrets/keycloak_client_secret"
                ),
                redirect_uri=os.getenv(
                    "PROXYLENS_REDIRECT_URI", "http://localhost:8001/oidc/callback"
                ),
                jwks_ttl=int(os.getenv("PROXYLENS_JWKS_TTL", "300")),
                refresh_interval=int(os.getenv("PROXYLENS_JWKS_REFRESH_INTERVAL", "15")),
                clock_skew=int(os.getenv("PROXYLENS_TOKEN_CLOCK_SKEW", "5")),
            ),
            projection=ProjectionSettings(
                cpamp_instance_id=cpamp_instance_id,
                cpa_instance_id=cpa_instance_id,
                keycloak_issuer=issuer,
                poll_seconds=int(os.getenv("PROXYLENS_PROJECTION_POLL_SECONDS", "30")),
                stale_after_ms=int(os.getenv("PROXYLENS_PROJECTION_STALE_MS", "60000")),
                overlap_ms=int(os.getenv("PROXYLENS_PROJECTION_OVERLAP_MS", "300000")),
                window_ms=int(os.getenv("PROXYLENS_PROJECTION_WINDOW_MS", "86400000")),
                reconcile_seconds=int(os.getenv("PROXYLENS_PROJECTION_RECONCILE_SECONDS", "3600")),
                retention_days=int(os.getenv("PROXYLENS_RETENTION_PROJECTION_DAYS", "90")),
                max_windows=int(os.getenv("PROXYLENS_PROJECTION_MAX_WINDOWS", "1000")),
            ),
            exporter=ExporterSettings(
                enabled=bool(langfuse_url),
                base_url=langfuse_url or "http://langfuse-web:3000",
                public_key_file=Path(
                    os.getenv(
                        "PROXYLENS_LANGFUSE_PUBLIC_KEY_FILE",
                        "/run/secrets/langfuse_public_key",
                    )
                ),
                secret_key_file=Path(
                    os.getenv(
                        "PROXYLENS_LANGFUSE_SECRET_KEY_FILE",
                        "/run/secrets/langfuse_secret_key",
                    )
                ),
                max_age_seconds=int(os.getenv("PROXYLENS_EXPORTER_MAX_AGE_SECONDS", "86400")),
                usage_wait_seconds=int(os.getenv("PROXYLENS_EXPORTER_USAGE_WAIT_SECONDS", "300")),
                retention_seconds=int(os.getenv("PROXYLENS_RETENTION_OUTBOX_DAYS", "90")) * 86400,
            ),
            retention=RetentionPolicy.from_environment(os.environ),
            worker_interval_seconds=float(os.getenv("PROXYLENS_WORKER_INTERVAL_SECONDS", "5")),
            retention_interval_seconds=float(
                os.getenv("PROXYLENS_RETENTION_INTERVAL_SECONDS", "3600")
            ),
            group_reconcile_interval_seconds=float(
                os.getenv("PROXYLENS_GROUP_RECONCILE_INTERVAL_SECONDS", "3600")
            ),
            completion_pending_seconds=int(
                os.getenv("PROXYLENS_COMPLETION_PENDING_SECONDS", "300")
            ),
            worker_scan_limit=int(os.getenv("PROXYLENS_WORKER_SCAN_LIMIT", "100")),
            worker_drain_limit=int(os.getenv("PROXYLENS_WORKER_DRAIN_LIMIT", "100")),
            projection_proof_files=proof_files,
            projection_proof_digests=proof_digests,
        )
