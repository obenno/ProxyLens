"""Signed identity + production application wiring, with real PostgreSQL."""

import asyncio
import os
from urllib.parse import urlsplit

import httpx
import pytest
from test_identity import G1, G2, ISSUER, claims, jwks, signed

from proxylens.app import create_app
from proxylens.db import Database

DSN = os.getenv(
    "PROXYLENS_GATEWAY_TEST_DSN",
    "postgres://proxylens_test:proxylens_test@127.0.0.1:55432/proxylens_gateway",
)


class IdentityServer:
    def __init__(self):
        self.groups = {G1: 0, G2: 0}
        self.offline = False

    def __call__(self, request):
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json=jwks())
        if self.offline:
            return httpx.Response(503, text="synthetic-admin-secret")
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "synthetic-admin-token"})
        if "/groups/" in request.url.path:
            group = request.url.path.rsplit("/", 1)[1]
            if group not in self.groups:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": group, "subGroupCount": self.groups[group]})
        return httpx.Response(200, json=[])


@pytest.fixture
def environment(monkeypatch, tmp_path):
    parsed = urlsplit(DSN)
    password = tmp_path / "db-password"
    password.write_text(parsed.password)
    admin = tmp_path / "admin-secret"
    admin.write_text("synthetic-admin-secret")
    cpa = tmp_path / "cpa-client"
    cpa.write_text("synthetic-service-client")
    for name, value in {
        "DB_HOST": parsed.hostname,
        "DB_PORT": str(parsed.port),
        "DB_USER": parsed.username,
        "DB_NAME": parsed.path[1:],
        "DB_PASSWORD_FILE": str(password),
        "KEYCLOAK_ISSUER": ISSUER,
        "KEYCLOAK_URL": "https://identity.example",
        "KEYCLOAK_CLIENT_SECRET_FILE": str(admin),
        "CPAMP_ADMIN_KEY_FILE": str(admin),
        "CPA_CLIENT_KEY_FILE": str(cpa),
    }.items():
        monkeypatch.setenv("PROXYLENS_" + name, value)
    db = Database(DSN)

    async def prepare():
        await db.migrate()
        async with db.transaction() as conn:
            await conn.execute(
                "TRUNCATE resource_audit, resource_rate_windows, resource_client_keys, "
                "resource_applications, resource_group_refs, lineage_ingress CASCADE"
            )

    asyncio.run(prepare())
    return db


def auth(role="group-admin", groups=(G1,)):
    return {
        "Authorization": "Bearer "
        + signed(
            claims(
                resource_access={"proxylens-api": {"roles": [role]}},
                proxylens_group_ids=list(groups),
            )
        )
    }


def test_signed_management_scope_and_flat_group_authority(environment):
    async def scenario():
        authority = IdentityServer()
        app = create_app("api", identity_transport=httpx.MockTransport(authority))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://api.example"
            ) as client,
        ):
            created = await client.post(
                "/api/applications", headers=auth(), json={"group_id": G1, "name": "Synthetic IDE"}
            )
            assert created.status_code == 201, created.text
            app_id = created.json()["id"]
            assert (
                await client.post(
                    "/api/applications", headers=auth(), json={"group_id": G2, "name": "Forbidden"}
                )
            ).status_code == 403
            member = await client.get("/api/applications", headers=auth("group-member"))
            assert [row["id"] for row in member.json()] == [app_id]
            assert (await client.get("/api/applications", headers=auth("member"))).json() == []
            assert (await client.get("/api/applications", headers=auth(groups=(G2,)))).json() == []
            assert (
                await client.get("/api/applications", headers=auth("platform-admin", ()))
            ).json()
            assert (
                await client.post(
                    f"/api/applications/{app_id}/keys", headers=auth("auditor"), json={}
                )
            ).status_code == 403
            issued = await client.post(f"/api/applications/{app_id}/keys", headers=auth(), json={})
            assert issued.status_code == 201
            listed = await client.get(
                f"/api/applications/{app_id}/keys", headers=auth("group-member")
            )
            assert issued.json()["plaintext"] not in listed.text
            authority.groups[G2] = 1
            nested = await client.post(
                "/api/applications",
                headers=auth("platform-admin", ()),
                json={"group_id": G2, "name": "Nested"},
            )
            assert nested.status_code in {403, 503}
            authority.offline = True
            assert (
                await client.post(f"/api/applications/{app_id}/keys", headers=auth(), json={})
            ).status_code == 503
            assert (
                await client.get("/api/applications", headers=auth("group-member"))
            ).status_code == 200

    asyncio.run(scenario())


def test_actual_identity_error_management_denial_is_audited(environment):
    async def scenario():
        authority = IdentityServer()
        app = create_app("api", identity_transport=httpx.MockTransport(authority))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://api.example"
            ) as client,
        ):
            response = await client.get("/api/applications")
            assert response.status_code == 401
            assert response.json() == {"error": "unauthenticated"}
        async with environment.transaction() as conn:
            denial = await (
                await conn.execute(
                    "SELECT actor, group_id, resource_id, outcome, details "
                    "FROM resource_audit WHERE action='management.denied' "
                    "ORDER BY occurred_at DESC LIMIT 1"
                )
            ).fetchone()
        assert denial == {
            "actor": None,
            "group_id": None,
            "resource_id": None,
            "outcome": "denied",
            "details": {"code": "unauthenticated"},
        }

    asyncio.run(scenario())


def test_worker_lifespan_constructs_and_stops_runtime_components(environment):
    async def scenario():
        authority = IdentityServer()
        app = create_app("worker", identity_transport=httpx.MockTransport(authority))
        async with app.router.lifespan_context(app):
            assert app.state.runtime.adapter is app.state.adapter
            assert app.state.runtime.projection is app.state.projection
            assert app.state.runtime.scanner is app.state.scanner
            assert app.state.runtime.supervisor is app.state.supervisor

    asyncio.run(scenario())
