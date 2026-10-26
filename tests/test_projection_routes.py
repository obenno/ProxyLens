import asyncio
from dataclasses import replace

import httpx
from fastapi import FastAPI
from test_identity import G1, G2, claims, jwks, signed
from test_identity import settings as identity_settings
from test_projection import (
    NOW,
    History,
    adapter,
    bind,
    event,
    proof_files,
    settings,
    synthetic_gate,
)
from test_projection import database as database

from proxylens.identity import GroupState
from proxylens.keycloak import KeycloakAuthority
from proxylens.oidc import IdentityService
from proxylens.projection import ProjectionRepository, ProjectionWorker
from proxylens.projection_routes import install_projection_routes
from proxylens.projection_settings import ProofGate, load_proof_gate
from proxylens.resources import ResourceRepository, VerifiedGroup


def token(groups=(G1,), roles=("group-member",)):
    return signed(
        claims(
            proxylens_group_ids=list(groups),
            resource_access={"proxylens-api": {"roles": list(roles)}},
        )
    )


def test_real_signed_identity_scopes_every_usage_path_and_live_orphan_state(database, tmp_path):
    async def scenario():
        config, clock = settings(retention_days=1), [NOW]
        repo = ProjectionRepository(database, config, clock_ms=lambda: clock[0])
        groups = {G1, G2}
        secret = tmp_path / "synthetic-admin-secret"
        secret.write_text("synthetic-test-value")

        def admin_http(request):
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "synthetic-token"})
            group_id = request.url.path.rsplit("/", 1)[-1]
            return (
                httpx.Response(200, json={"id": group_id, "subGroupCount": 0})
                if (group_id in groups)
                else httpx.Response(404)
            )

        async def lookup(group_id):
            async with httpx.AsyncClient(transport=httpx.MockTransport(admin_http)) as client:
                authority = KeycloakAuthority(
                    identity_settings(admin_secret_file=str(secret)),
                    client,
                )
                evidence = await authority.lookup_group(group_id)
                return (
                    VerifiedGroup(evidence.group_id)
                    if evidence.state == GroupState.ACTIVE
                    else None
                )

        resources = ResourceRepository(database, lookup)
        a1 = await resources.create_application(G1, "one", actor="admin")
        a2 = await resources.create_application(G2, "two", actor="admin")
        await bind(database, G1, a1["id"])
        other_native = "019a96c4-0c00-7000-8000-0123456789ac"
        await bind(database, G2, a2["id"], other_native)
        history = History([event(1), event(2, request_id=other_native)])
        gate = synthetic_gate(tmp_path, config)
        async with adapter(history, config, clock) as source:
            assert await ProjectionWorker(
                repo, source, gate=gate, clock_ms=lambda: clock[0]
            ).poll_once()
        app = FastAPI()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=jwks())),
        ) as identity_http:
            app.state.identity = IdentityService(identity_settings(), identity_http)
            install_projection_routes(app, repo, gate=gate)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://test",
            ) as client:
                assert (await client.get("/api/usage")).status_code == 401
                client.headers["Authorization"] = "Bearer invalid"
                assert (await client.get("/api/usage")).status_code == 401
                client.headers["Authorization"] = "Bearer " + token()
                result = await client.get("/api/usage")
                assert result.status_code == 200, result.text
                assert result.headers["cache-control"] == "no-store"
                body = result.json()
                assert [r["group_id"] for r in body["records"]] == [G1]
                assert body["totals"]["observed_records"] == 1
                assert body["totals"]["total_records"] is None
                assert body["totals"]["observed_tokens"] == 140
                assert body["totals"]["cost"] is None
                assert body["coverage"] == "unknown"
                assert "coverage_details" not in body["health"]
                assert "duplicate_count" not in body["health"]
                other_config = replace(config, cpa_instance_id="another-cpa")
                other_app = FastAPI()
                other_app.state.identity = app.state.identity
                install_projection_routes(
                    other_app,
                    ProjectionRepository(database, other_config),
                    gate=synthetic_gate(tmp_path, other_config),
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(other_app),
                    base_url="http://other",
                    headers={"Authorization": "Bearer " + token()},
                ) as other_client:
                    assert (await other_client.get("/api/usage")).status_code == 503
                assert (await client.get(f"/api/groups/{G2}/usage")).status_code == 403
                assert (await client.get(f"/api/applications/{a2['id']}/usage")).status_code == 404
                assert (await client.get(f"/api/usage/records/{2:064x}")).status_code == 404
                assert (await client.get("/api/usage/totals?group_id=" + G2)).status_code == 403
                assert (await client.get("/api/usage?limit=1&offset=1")).json()["records"] == []
                for roles, scope in [((), (G1,)), (("auditor",), ())]:
                    client.headers["Authorization"] = "Bearer " + token(scope, roles)
                    response = await client.get(f"/api/groups/{G1}/usage")
                    assert response.status_code == 403
                for roles in [("group-member",), ("auditor",), ("platform-admin",)]:
                    client.headers["Authorization"] = "Bearer " + token((G1, G2), roles)
                    response = await client.get("/api/usage")
                    assert len(response.json()["records"]) == 2
                client.headers["Authorization"] = "Bearer " + token()
                groups.remove(G1)
                await resources.reconcile_group(G1, actor="admin")
                row = (await client.get(f"/api/usage/records/{1:064x}")).json()
                assert row["orphaned"] is True
                assert row["group_id"] == G1
                repaired = await resources.reassign_orphan(a1["id"], G2, actor="admin")
                row = (await client.get(f"/api/usage/records/{1:064x}")).json()
                assert row["application_id"] == a1["id"]
                assert row["group_id"] == G1
                assert row["orphaned"] is True
                assert repaired["id"] != a1["id"]
                await bind(database, G2, a2["id"])
                assert (await client.get(f"/api/usage/records/{1:064x}")).status_code == 404
                empty = (await client.get("/api/usage/totals")).json()
                assert empty["observed_records"] == 0
                assert empty["total_records"] is None
                assert empty["observed_tokens"] is None

    asyncio.run(scenario())


def test_every_tenant_route_is_disabled_without_both_live_proofs(database, tmp_path):
    async def scenario():
        config = settings()
        paths, approvals = proof_files(tmp_path, config)
        gates = [
            ProofGate(),
            load_proof_gate(
                config,
                paths[:1],
                approved_sha256=approvals,
                allow_synthetic=True,
            ),
            load_proof_gate(config, paths, approved_sha256=approvals),
        ]
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=jwks())),
        ) as identity_http:
            for gate in gates:
                app = FastAPI()
                app.state.identity = IdentityService(identity_settings(), identity_http)
                install_projection_routes(app, ProjectionRepository(database, config), gate=gate)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app),
                    base_url="http://test",
                    headers={"Authorization": "Bearer " + token()},
                ) as client:
                    for path in [
                        "/api/usage",
                        "/api/usage/totals",
                        f"/api/groups/{G1}/usage",
                        f"/api/applications/{G1}/usage",
                        f"/api/usage/records/{1:064x}",
                    ]:
                        response = await client.get(path)
                        assert response.status_code == 503
                        assert response.json()["error"] == "tenant_usage_disabled"
                        assert "records" not in response.json()

    asyncio.run(scenario())
