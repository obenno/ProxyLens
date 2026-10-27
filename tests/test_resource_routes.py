import asyncio
import socket
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, HTTPException
from test_resources import database as database
from test_resources import lookup

from proxylens.db import Database
from proxylens.identity import IdentityError
from proxylens.resource_routes import ResourceAccess, install_resource_routes
from proxylens.resources import ResourceRepository


@dataclass(frozen=True)
class VerifiedTestPrincipal:
    subject: str
    groups: frozenset[str]
    roles: frozenset[str]


def access():
    """Only the identity test seam is stubbed; resource storage and routes are real."""
    return ResourceAccess(
        actor=lambda p: p.subject,
        read_groups=lambda p: (
            None
            if "platform-admin" in p.roles
            else p.groups
            if p.roles & {"member", "group-admin", "auditor"}
            else frozenset()
        ),
        can_manage=lambda p, g: "group-admin" in p.roles and g in p.groups,
        is_platform_admin=lambda p: "platform-admin" in p.roles,
        can_audit=lambda p: bool(p.roles & {"group-admin", "auditor"}),
    )


def test_scoped_http_routes_separate_capability_and_group_scope(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        principals = {
            "admin": VerifiedTestPrincipal("a1", frozenset({"g1"}), frozenset({"group-admin"})),
            "member": VerifiedTestPrincipal("m1", frozenset({"g1"}), frozenset({"member"})),
            "multi": VerifiedTestPrincipal("m12", frozenset({"g1", "g2"}), frozenset({"member"})),
            "platform": VerifiedTestPrincipal("pa", frozenset(), frozenset({"platform-admin"})),
            "role-only": VerifiedTestPrincipal("a0", frozenset(), frozenset({"group-admin"})),
            "group-only": VerifiedTestPrincipal("g0", frozenset({"g1"}), frozenset()),
            "auditor": VerifiedTestPrincipal("au", frozenset({"g1"}), frozenset({"auditor"})),
        }
        current = [principals["admin"]]

        async def principal_dependency():
            if current[0] is None:
                raise HTTPException(401, "unauthenticated")
            return current[0]

        app = FastAPI()
        install_resource_routes(
            app, repo, principal_dependency=principal_dependency, access=access()
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            r = await client.post("/api/applications", json={"group_id": "g1", "name": "CLI"})
            assert r.status_code == 201, r.text
            app1 = r.json()["id"]
            assert (
                await client.post("/api/applications", json={"group_id": "g2", "name": "hidden"})
            ).status_code == 403
            current[0] = principals["platform"]
            r = await client.post("/api/applications", json={"group_id": "g2", "name": "G2"})
            assert r.status_code == 201
            app2 = r.json()["id"]
            assert (
                await client.post(
                    "/api/applications", json={"group_id": "missing", "name": "missing"}
                )
            ).status_code == 409
            current[0] = principals["admin"]
            assert (await client.get(f"/api/applications/{app2}")).status_code == 404
            assert (await client.post(f"/api/applications/{app2}/keys", json={})).status_code == 403
            assert (
                await client.put(f"/api/applications/{app2}/policy", json={"models": ["m1"]})
            ).status_code == 403
            assert (
                await client.put("/api/groups/g2/policy", json={"models": ["m1"]})
            ).status_code == 403
            assert (
                await client.post(f"/api/applications/{app1}/keys", json={"group_id": "g2"})
            ).status_code == 422
            issued = await client.post(f"/api/applications/{app1}/keys", json={})
            assert issued.status_code == 201
            secret = issued.json()["plaintext"]
            assert issued.headers["cache-control"] == "no-store"
            for role in ("member", "auditor", "role-only", "group-only"):
                current[0] = principals[role]
                assert (
                    await client.post(f"/api/applications/{app1}/keys", json={})
                ).status_code == 403
                assert (
                    await client.post("/api/applications", json={"group_id": "g1", "name": "bad"})
                ).status_code == 403
            current[0] = principals["member"]
            rows = (await client.get("/api/applications")).json()
            assert [row["id"] for row in rows] == [app1]
            assert (await client.get("/api/applications?group_id=g2")).status_code == 404
            assert secret not in (await client.get(f"/api/applications/{app1}/keys")).text
            assert (await client.get("/api/resource-audit")).status_code == 403
            current[0] = principals["multi"]
            assert len((await client.get("/api/applications")).json()) == 2
            current[0] = principals["auditor"]
            events = (await client.get("/api/resource-audit")).json()
            assert events and all(event["group_id"] == "g1" for event in events)
            assert secret not in str(events)
            current[0] = None
            assert (await client.get("/api/applications")).status_code == 401
        events = await repo.list_audit(None)
        assert any(event["outcome"] == "denied" and event["actor"] == "a1" for event in events)

    asyncio.run(scenario())


def test_http_lifecycle_rejects_cross_application_ids_and_audits_authentication_denials(database):
    async def scenario():
        groups = {"g1", "g2"}

        async def keycloak(group_id):
            return await lookup(group_id) if group_id in groups else None

        repo = ResourceRepository(database, keycloak)
        pa = VerifiedTestPrincipal("pa", frozenset(), frozenset({"platform-admin"}))
        current = [pa]

        async def identity():
            if current[0] is None:
                raise IdentityError("authentication_required")
            return current[0]

        app = FastAPI()
        install_resource_routes(app, repo, principal_dependency=identity, access=access())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            a1 = (
                await client.post("/api/applications", json={"group_id": "g1", "name": "a1"})
            ).json()["id"]
            a2 = (
                await client.post("/api/applications", json={"group_id": "g2", "name": "a2"})
            ).json()["id"]
            first = (await client.post(f"/api/applications/{a1}/keys", json={})).json()
            kid = first["key"]["id"]
            assert (
                await client.post(f"/api/applications/{a2}/keys/{kid}/revoke")
            ).status_code == 404
            assert (
                await client.post(f"/api/applications/{a2}/keys/{kid}/rotate", json={})
            ).status_code == 409
            assert (
                await client.post(
                    f"/api/applications/{a1}/keys", json={"expires_at": "2000-01-01T00:00:00Z"}
                )
            ).status_code == 422
            rotated = await client.post(f"/api/applications/{a1}/keys/{kid}/rotate", json={})
            assert rotated.status_code == 201
            assert first["plaintext"] not in rotated.text
            assert (
                await client.post(f"/api/applications/{a1}/keys/{kid}/rotate", json={})
            ).status_code == 409
            groups.remove("g1")
            assert (await client.post("/api/groups/g1/reconcile")).json()["state"] == "orphaned"
            assert (await client.post(f"/api/applications/{a1}/keys", json={})).status_code == 409
            repair = await client.post(
                f"/api/applications/{a1}/reassign", json={"target_group_id": "g2"}
            )
            assert repair.status_code == 201
            assert repair.json()["predecessor_id"] == a1
            assert (await client.get(f"/api/applications/{a1}")).json()["group_id"] == "g1"
            assert (await client.post(f"/api/applications/{a2}/revoke")).json()[
                "state"
            ] == "revoked"
            current[0] = None
            assert (
                await client.post(
                    "/api/applications", json={"group_id": "g2", "name": "unauthenticated"}
                )
            ).status_code == 401
        denials = [event for event in await repo.list_audit(None) if event["actor"] is None]
        assert len(denials) == 1
        assert denials[0]["group_id"] is None and denials[0]["resource_id"] is None
        assert denials[0]["outcome"] == "denied"

    asyncio.run(scenario())


def test_storage_and_keycloak_outages_fail_closed_without_mutation(database):
    async def scenario():
        current = VerifiedTestPrincipal("pa", frozenset(), frozenset({"platform-admin"}))

        async def identity():
            return current

        async def outage(_):
            raise TimeoutError("SENTINEL-PRIVILEGED-SECRET")

        repo = ResourceRepository(database, outage)
        app = FastAPI()
        install_resource_routes(app, repo, principal_dependency=identity, access=access())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            result = await client.post("/api/applications", json={"group_id": "g1", "name": "bad"})
            assert result.status_code == 503
            assert "SENTINEL" not in result.text
        assert await repo.list_applications(None) == []
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            bad = ResourceRepository(
                Database(host="127.0.0.1", port=unavailable.getsockname()[1]), lookup
            )
            app = FastAPI()
            install_resource_routes(app, bad, principal_dependency=identity, access=access())
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                result = await client.post(
                    "/api/applications", json={"group_id": "g1", "name": "bad"}
                )
                assert result.status_code == 503
                assert result.json() == {"error": "storage_unavailable"}
        assert await repo.list_applications(None) == []

    asyncio.run(scenario())


def test_identity_denial_audit_storage_failure_returns_redacted_503():
    async def scenario():
        with socket.socket() as unavailable:
            unavailable.bind(("127.0.0.1", 0))
            repo = ResourceRepository(
                Database(host="127.0.0.1", port=unavailable.getsockname()[1]), lookup
            )

        async def identity():
            raise IdentityError("authentication_required")

        app = FastAPI()
        install_resource_routes(app, repo, principal_dependency=identity, access=access())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/api/applications")
        assert response.status_code == 503
        assert response.json() == {"error": "storage_unavailable"}
        assert "authentication_required" not in response.text

    asyncio.run(scenario())


def test_role_mapping_can_limit_management_to_one_of_multiple_readable_groups(database):
    async def scenario():
        repo = ResourceRepository(database, lookup)
        app1 = await repo.create_application("g1", "managed", actor="pa")
        app2 = await repo.create_application("g2", "member only", actor="pa")
        principal = VerifiedTestPrincipal(
            "multi", frozenset({"g1", "g2"}), frozenset({"member", "group-admin"})
        )

        async def identity():
            return principal

        scoped_access = ResourceAccess(
            actor=lambda p: p.subject,
            read_groups=lambda p: p.groups,
            can_manage=lambda p, group: group == "g1",
            is_platform_admin=lambda p: False,
        )
        app = FastAPI()
        install_resource_routes(app, repo, principal_dependency=identity, access=scoped_access)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.get(f"/api/applications/{app2['id']}")).status_code == 200
            assert (
                await client.post(f"/api/applications/{app2['id']}/keys", json={})
            ).status_code == 403
            assert (
                await client.post(f"/api/applications/{app1['id']}/keys", json={})
            ).status_code == 201

    asyncio.run(scenario())
