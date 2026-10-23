"""Nonsecret configuration and explicit file-based secret access."""

import os
from dataclasses import dataclass
from pathlib import Path


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
        )
