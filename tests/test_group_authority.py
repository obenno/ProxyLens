import asyncio

import httpx
import pytest
from fastapi import HTTPException
from test_identity import G1, G2, ISSUER, claims, jwks, settings, signed

from proxylens.identity import AuthorityUnavailable, Capability, GroupState, require_group
from proxylens.keycloak import KeycloakAuthority, TokenVerifier


def test_live_group_lookup_reconciliation_distinguishes_deletion_from_outage(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("admin-secret-sentinel")
    status = [200]
    group = [{"id": G1, "name": "renamed", "parentId": None, "subGroupCount": 0}]
    observed = []

    def handle(request):
        observed.append(request)
        if request.url.path.endswith("/token"):
            assert b"client_id=proxylens-admin" in request.content
            assert b"admin-secret-sentinel" in request.content
            return httpx.Response(200, json={"access_token": "admin-token-sentinel"})
        assert request.headers["authorization"] == "Bearer admin-token-sentinel"
        return httpx.Response(status[0], json=group[0])

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            authority = KeycloakAuthority(settings(admin_secret_file=str(secret)), client)
            evidence = await authority.lookup_group(G1)
            assert evidence.state == GroupState.ACTIVE
            assert evidence.group_id == G1 and evidence.issuer == ISSUER
            marked = []

            async def mark(item):
                marked.append(item)

            status[0] = 404
            await authority.reconcile([G1], mark)
            assert [item.group_id for item in marked] == [G1]
            assert marked[0].state == GroupState.MISSING
            status[0] = 503
            with pytest.raises(AuthorityUnavailable):
                await authority.reconcile([G2], mark)
            assert len(marked) == 1
            status[0] = 200
            group[0] = {"id": G2, "name": "renamed", "subGroupCount": 0}
            with pytest.raises(AuthorityUnavailable):
                await authority.lookup_group(G1)
            group[0] = {"id": G1, "name": "child", "parentId": G2, "subGroupCount": 0}
            assert (await authority.lookup_group(G1)).state == GroupState.NESTED

    asyncio.run(check())
    assert all("/users/" not in str(request.url) for request in observed)


def test_management_requires_live_group_authority_read_remains_locally_verified(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("secret")

    def handle(request):
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json=jwks())
        raise httpx.ConnectError("offline")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            authority = KeycloakAuthority(settings(admin_secret_file=str(secret)), client)
            principal = await TokenVerifier(settings(), client).validate(
                signed(
                    claims(
                        resource_access={"proxylens-api": {"roles": ["group-admin"]}},
                        proxylens_group_ids=[G1],
                    )
                )
            )
            await require_group(principal, Capability.READ, G1, authority)
            with pytest.raises(AuthorityUnavailable):
                await require_group(principal, Capability.MANAGE, G1, authority)
            with pytest.raises(HTTPException) as denied:
                await require_group(principal, Capability.MANAGE, G2, authority)
            assert denied.value.status_code == 403

    asyncio.run(check())
