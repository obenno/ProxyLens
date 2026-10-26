import asyncio
import base64
import hashlib
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest
from fastapi import Depends
from test_identity import ISSUER, SUBJECT, claims, jwks, signed

from proxylens.app import create_app
from proxylens.identity import (
    Capability,
    Principal,
    get_group_authority,
    get_principal,
    require_group,
)


@pytest.mark.parametrize(
    "fault", [None, "state", "nonce", "exchange", "subject", "issuer", "offline"]
)
def test_browser_code_pkce_session_and_failures(monkeypatch, tmp_path, fault, environment):
    secret = tmp_path / "admin-secret"
    secret.write_text("admin-secret-sentinel")
    monkeypatch.setenv("PROXYLENS_KEYCLOAK_CLIENT_SECRET_FILE", str(secret))
    monkeypatch.setenv("PROXYLENS_KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("PROXYLENS_KEYCLOAK_URL", "https://identity.example")
    monkeypatch.setenv("PROXYLENS_REDIRECT_URI", "https://api.example/oidc/callback")
    authorization = [{}]
    exchanges = []

    def handle(request):
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json=jwks())
        if "/admin/" in request.url.path:
            if "/groups/" in request.url.path:
                return httpx.Response(
                    200, json={"id": request.url.path.rsplit("/", 1)[1], "subGroupCount": 0}
                )
            return httpx.Response(200, json=[])
        data = parse_qs(request.content.decode())
        if data.get("grant_type") == ["client_credentials"]:
            if fault == "offline":
                raise httpx.ConnectError("offline")
            return httpx.Response(200, json={"access_token": "admin-only"})
        exchanges.append(data)
        assert data["client_id"] == ["proxylens-browser"]
        assert "client_secret" not in data
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"][0].encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert authorization[0]["code_challenge"] == [challenge]
        if fault == "exchange":
            return httpx.Response(400, json={"error": "sentinel-upstream-error"})
        identity = claims(
            aud="proxylens-browser",
            typ="ID",
            nonce="tampered" if fault == "nonce" else authorization[0]["nonce"][0],
        )
        if fault == "subject":
            identity["sub"] = "22222222-2222-4222-8222-222222222222"
        return httpx.Response(200, json={"access_token": signed(), "id_token": signed(identity)})

    async def check():
        app = create_app("api", identity_transport=httpx.MockTransport(handle))
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://api.example"
            ) as client,
        ):
            assert (await client.get("/api/me")).status_code == 401
            login = await client.get("/oidc/login")
            if fault == "offline":
                assert login.status_code == 503
                return
            assert login.status_code == 302
            assert "admin-secret-sentinel" not in login.text + str(login.headers)
            authorization[0] = parse_qs(urlparse(login.headers["location"]).query)
            assert authorization[0]["response_type"] == ["code"]
            assert authorization[0]["code_challenge_method"] == ["S256"]
            query = {
                "state": "wrong" if fault == "state" else authorization[0]["state"][0],
                "iss": "https://wrong" if fault == "issuer" else ISSUER,
                "code": "one-time",
            }
            callback = await client.get("/oidc/callback?" + urlencode(query))
            if fault:
                assert callback.status_code in {401, 503}
                assert (await client.get("/api/me")).status_code == 401
            else:
                assert callback.status_code == 200
                assert callback.json()["subject"] == SUBJECT
                assert (await client.get("/api/me")).json()["subject"] == SUBJECT
                assert "HttpOnly" in callback.headers["set-cookie"]
                assert "Secure" in callback.headers["set-cookie"]
                assert (await client.post("/oidc/logout")).status_code == 403
                logout = await client.post(
                    "/oidc/logout",
                    headers={
                        "Origin": "https://api.example",
                        "X-Proxylens-CSRF": callback.json()["csrf_token"],
                    },
                )
                assert logout.status_code == 204
                assert (await client.get("/api/me")).status_code == 401
            assert "sentinel" not in callback.text
            assert (await client.get("/oidc/callback?" + urlencode(query))).status_code == 401

    asyncio.run(check())


def test_protected_dependency_denies_mutation_and_reports_authority_outage(
    monkeypatch, tmp_path, environment
):
    secret = tmp_path / "secret"
    secret.write_text("secret")
    monkeypatch.setenv("PROXYLENS_KEYCLOAK_CLIENT_SECRET_FILE", str(secret))
    monkeypatch.setenv("PROXYLENS_KEYCLOAK_ISSUER", ISSUER)
    offline = [False]
    changed = []

    def handle(request):
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json=jwks())
        if offline[0]:
            raise httpx.ConnectError("offline")
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "admin-only"})
        if "/groups/" in request.url.path:
            return httpx.Response(
                200, json={"id": request.url.path.rsplit("/", 1)[1], "subGroupCount": 0}
            )
        return httpx.Response(200, json=[])

    async def check():
        app = create_app("api", identity_transport=httpx.MockTransport(handle))

        @app.post("/test/groups/{group_id}")
        async def mutation(
            group_id: str,
            principal: Annotated[Principal, Depends(get_principal)],
            authority: Annotated[object, Depends(get_group_authority)],
        ):
            await require_group(principal, Capability.MANAGE, group_id, authority)
            changed.append(group_id)
            return {"ok": True}

        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://api.example"
            ) as client,
        ):
            from test_identity import G1, G2

            endpoint = "/test/groups/" + G1
            assert (await client.post(endpoint)).status_code == 401
            assert (
                await client.post(endpoint, headers={"Authorization": "Bearer malformed"})
            ).status_code == 401
            auditor = signed(claims(resource_access={"proxylens-api": {"roles": ["auditor"]}}))
            assert (
                await client.post(endpoint, headers={"Authorization": "Bearer " + auditor})
            ).status_code == 403
            admin = signed(
                claims(
                    resource_access={"proxylens-api": {"roles": ["group-admin"]}},
                    proxylens_group_ids=[G1],
                )
            )
            headers = {"Authorization": "Bearer " + admin}
            assert (await client.post("/test/groups/" + G2, headers=headers)).status_code == 403
            assert changed == []
            assert (await client.post(endpoint, headers=headers)).status_code == 200
            offline[0] = True
            assert (await client.get("/api/me", headers=headers)).status_code == 200
            assert (await client.post(endpoint, headers=headers)).status_code == 503
            assert (await client.get("/oidc/login")).status_code == 503
            assert changed == [G1]

    asyncio.run(check())
