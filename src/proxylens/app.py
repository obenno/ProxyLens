"""Runnable role entrypoints. Business routes and background jobs land in later issues."""

import asyncio

import httpx
import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from proxylens.config import Settings, secret_file


async def database_ready(settings: Settings) -> bool:
    try:
        async with asyncio.timeout(3):
            async with await psycopg.AsyncConnection.connect(
                host=settings.db_host,
                port=settings.db_port,
                dbname=settings.db_name,
                user=settings.db_user,
                password=secret_file(
                    "PROXYLENS_DB_PASSWORD_FILE", "/run/secrets/postgres_password"
                ),
                connect_timeout=2,
                options="-c statement_timeout=2000",
            ) as connection:
                await connection.execute("SELECT 1")
        return True
    except (OSError, ValueError, psycopg.Error, TimeoutError):
        return False


async def http_ready(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            response = await client.get(url)
            return response.status_code == 200
    except httpx.HTTPError:
        return False


def create_app(role: str) -> FastAPI:
    if role not in {"api", "gateway", "worker"}:
        raise ValueError("role must be api, gateway, or worker")
    settings = Settings.from_environment()
    app = FastAPI(title=f"ProxyLens {role}", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    async def live():
        return {"status": "live", "role": role, "stage": "foundation"}

    @app.get("/health/ready")
    async def ready():
        probes = {"postgres": database_ready(settings)}
        if role in {"api", "gateway"}:
            probes["keycloak"] = http_ready(
                f"{settings.keycloak_url}/realms/proxylens/.well-known/openid-configuration"
            )
        if role == "gateway":
            probes["cliproxyapi"] = http_ready(f"{settings.cpa_url}/healthz")
        if role == "worker":
            probes["cpamp"] = http_ready(f"{settings.cpamp_url}/health")
        results = await asyncio.gather(*probes.values())
        dependencies = dict(
            zip(probes, ("ready" if ok else "unavailable" for ok in results), strict=True)
        )
        return JSONResponse(
            status_code=200 if all(results) else 503,
            content={
                "status": "ready" if all(results) else "unavailable",
                "role": role,
                "stage": "foundation",
                "dependencies": dependencies,
            },
        )

    return app
