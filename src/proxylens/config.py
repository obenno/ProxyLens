"""Nonsecret configuration and explicit file-based secret access."""

import os
from dataclasses import dataclass
from pathlib import Path

from proxylens.db import Database
from proxylens.gateway import GatewaySettings
from proxylens.keycloak import IdentitySettings


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

    def database(self) -> Database:
        return Database(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password_file=os.getenv("PROXYLENS_DB_PASSWORD_FILE", "/run/secrets/postgres_password"),
        )

    @classmethod
    def from_environment(cls) -> "Settings":
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
                issuer=os.getenv(
                    "PROXYLENS_KEYCLOAK_ISSUER", "http://localhost:8080/realms/proxylens"
                ),
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
        )
