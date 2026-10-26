"""Gateway public contract using production persistence and local TCP servers."""

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
import uvicorn
from test_application_wiring import IdentityServer, auth
from test_identity import G1

from proxylens.app import create_app

NATIVE = "019a96c4-0c00-7000-8000-0123456789ab"
TRACE = "20261024000000-synthetic_account-" + NATIVE


@asynccontextmanager
async def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_level="critical",
            access_log=False,
            lifespan="on" if hasattr(app, "router") else "off",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    task.result()
                    raise RuntimeError("server did not start")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


async def issue(identity, *, policy=None):
    app = create_app("api", identity_transport=httpx.MockTransport(identity))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.example", headers=auth()
        ) as client,
    ):
        created = await client.post("/api/applications", json={"group_id": G1, "name": "IDE"})
        assert created.status_code == 201
        app_id = created.json()["id"]
        result = await client.put(
            "/api/groups/" + G1 + "/policy",
            json=policy or {"models": ["demo", "resolved-demo"], "providers": ["codex"]},
        )
        assert result.status_code == 200
        key = await client.post(f"/api/applications/{app_id}/keys", json={})
        assert key.status_code == 201
        return key.json(), app_id


def routing(monkeypatch, tmp_path):
    path = tmp_path / "routing.json"
    path.write_text(
        json.dumps({"demo": {"model": "resolved-demo", "provider": "codex", "verified": True}})
    )
    monkeypatch.setenv("PROXYLENS_ROUTING_REGISTRY", str(path))


def test_stream_first_byte_lineage_payload_and_service_credential(
    environment, monkeypatch, tmp_path
):
    routing(monkeypatch, tmp_path)

    async def scenario():
        identity = IdentityServer()
        key, app_id = await issue(identity)
        first_received = asyncio.Event()
        calls = []
        first = b'event: response.output_item.added\ndata: {"type":"function_call"}\n\n'
        last = b'data: {"type":"response.completed"}\n\n'
        payload = {
            "model": "demo",
            "stream": True,
            "tools": [{"type": "function", "name": "demo"}],
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": "data:image/png;base64,c3ludGhldGlj"}
                    ],
                }
            ],
            "metadata": {"content-sentinel": "never-persist"},
        }

        async def upstream(scope, receive, send):
            body = bytearray()
            while True:
                message = await receive()
                body.extend(message.get("body", b""))
                if not message.get("more_body"):
                    break
            headers = dict(scope["headers"])
            calls.append((bytes(body), headers))
            assert headers[b"authorization"] == b"Bearer synthetic-service-client"
            assert b"x-subject" not in headers
            async with environment.transaction() as conn:
                row = await (
                    await conn.execute(
                        "SELECT * FROM lineage_ingress WHERE request_id = %s",
                        (headers[b"x-request-id"].decode(),),
                    )
                ).fetchone()
            assert row is not None and row["application_id"] == app_id
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/event-stream"),
                        (b"x-cpa-trace-id", TRACE.encode()),
                        (b"x-internal-secret", b"synthetic-private"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": first, "more_body": True})
            await asyncio.wait_for(first_received.wait(), 3)
            await send({"type": "http.response.body", "body": last, "more_body": False})

        async with serve(upstream) as url:
            monkeypatch.setenv("PROXYLENS_CPA_URL", url)
            gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
            async with serve(gateway) as base, httpx.AsyncClient(timeout=5) as client:  # noqa: SIM117
                async with client.stream(
                    "POST",
                    base + "/v1/responses",
                    json=payload,
                    headers={
                        "Authorization": "Bearer " + key["plaintext"],
                        "X-Subject": "untrusted",
                        "X-Request-ID": "untrusted",
                        "X-Application-ID": "untrusted",
                    },
                ) as response:
                    assert response.status_code == 200
                    assert response.headers["x-cpa-request-id"] == NATIVE
                    ingress = response.headers["x-request-id"]
                    assert UUID(ingress).version == 4
                    assert "x-cpa-trace-id" not in response.headers
                    assert "synthetic" not in str(response.headers)
                    chunks = response.aiter_raw()
                    assert await anext(chunks) == first
                    first_received.set()
                    assert b"".join([chunk async for chunk in chunks]) == last
        assert len(calls) == 1 and json.loads(calls[0][0]) == payload
        async with environment.transaction() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM gateway_lifecycle WHERE request_id = %s", (ingress,)
                )
            ).fetchone()
            native = await (
                await conn.execute(
                    "SELECT * FROM lineage_native_binding WHERE request_id = %s", (ingress,)
                )
            ).fetchone()
        assert str(native["cpa_request_id"]) == NATIVE
        assert row["outcome"] == "completed" and row["http_status"] == 200
        assert row["requested_model"] == "demo" and row["duration_ms"] >= 0
        assert "never-persist" not in str(row) and key["plaintext"] not in str(row)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault", ["none", "at-limit", "over-limit", "db-down", "connect-error", "unknown-error"]
)
def test_nonstreaming_global_limits_and_dependency_errors(
    environment, monkeypatch, tmp_path, fault
):
    routing(monkeypatch, tmp_path)
    body = b'{"model":"demo","input":"synthetic"}'
    if fault in {"at-limit", "over-limit"}:
        monkeypatch.setenv("PROXYLENS_MAX_BODY_BYTES", str(len(body) - (fault == "over-limit")))

    async def scenario():
        identity = IdentityServer()
        key, _ = await issue(identity)
        calls = []

        async def upstream(scope, receive, send):
            while (await receive()).get("more_body"):
                pass
            calls.append(scope)
            await send(
                {
                    "type": "http.response.start",
                    "status": 201,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {"type": "http.response.body", "body": b'{"id":"synthetic-response","output":[]}'}
            )

        async with serve(upstream) as url:
            monkeypatch.setenv("PROXYLENS_CPA_URL", url)
            gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
            async with serve(gateway) as base, httpx.AsyncClient() as client:
                if fault == "db-down":
                    # Real refused PostgreSQL connection, not a repository mock.
                    from proxylens.db import Database

                    dead = socket.socket()
                    dead.bind(("127.0.0.1", 0))
                    monkeypatch.setattr(
                        gateway.state.resources,
                        "database",
                        Database(host="127.0.0.1", port=dead.getsockname()[1], connect_timeout=1),
                    )
                if fault in {"connect-error", "unknown-error"}:

                    async def fail(request):
                        if fault == "connect-error":
                            raise httpx.ConnectError("synthetic-sensitive-error")
                        raise RuntimeError("synthetic-sensitive-error")

                    transport = httpx.AsyncClient(transport=httpx.MockTransport(fail))
                    monkeypatch.setattr(gateway.state.gateway, "client", transport)
                try:
                    response = await client.post(
                        base + "/v1/responses",
                        content=body,
                        headers={
                            "Authorization": "Bearer " + key["plaintext"],
                            "Content-Type": "application/json",
                        },
                    )
                finally:
                    if fault == "db-down":
                        dead.close()
                    if fault in {"connect-error", "unknown-error"}:
                        await transport.aclose()
                expected = {
                    "over-limit": 413,
                    "db-down": 503,
                    "connect-error": 502,
                    "unknown-error": 500,
                }.get(fault, 201)
                assert response.status_code == expected
                if expected == 201:
                    assert response.content == b'{"id":"synthetic-response","output":[]}'
                else:
                    assert "synthetic" not in response.text
        assert len(calls) == (1 if fault in {"none", "at-limit"} else 0)

    asyncio.run(scenario())


def test_native_collision_and_client_ids_never_overwrite_ownership(
    environment, monkeypatch, tmp_path
):
    routing(monkeypatch, tmp_path)

    async def scenario():
        identity = IdentityServer()
        first, first_app = await issue(identity)
        second, second_app = await issue(identity)
        calls = []

        async def upstream(scope, receive, send):
            while (await receive()).get("more_body"):
                pass
            calls.append(scope)
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"x-cpa-trace-id", TRACE.encode())],
                }
            )
            await send({"type": "http.response.body", "body": b"{}"})

        async with serve(upstream) as url:
            monkeypatch.setenv("PROXYLENS_CPA_URL", url)
            gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
            async with serve(gateway) as base, httpx.AsyncClient() as client:
                ids = []
                for key in (first, second):
                    response = await client.post(
                        base + "/v1/responses",
                        json={"model": "demo"},
                        headers={
                            "Authorization": "Bearer " + key["plaintext"],
                            "X-Request-ID": "same-client-id",
                        },
                    )
                    assert response.status_code == 200
                    ids.append(response.headers["x-request-id"])
        assert len(calls) == 2 and len(set(ids)) == 2
        from proxylens.correlation import UsageIdentity
        from proxylens.lineage import LineageRepository

        async with environment.transaction() as conn:
            rows = await (
                await conn.execute("SELECT application_id FROM lineage_ingress")
            ).fetchall()
            assert {row["application_id"] for row in rows} == {first_app, second_app}
            result = await LineageRepository(conn).record_event(
                UsageIdentity.from_cpamp("synthetic-cpamp", "a" * 64, "primary", NATIVE)
            )
            assert result.status == "ambiguous" and result.ingress is None

    asyncio.run(scenario())


def test_shared_rate_caps_and_next_request_revocation(environment, monkeypatch, tmp_path):
    routing(monkeypatch, tmp_path)

    async def scenario():
        identity = IdentityServer()
        key, app_id = await issue(
            identity,
            policy={
                "models": ["demo", "resolved-demo"],
                "providers": ["codex"],
                "key_requests_per_minute": 1,
                "application_requests_per_minute": 2,
            },
        )
        api = create_app("api", identity_transport=httpx.MockTransport(identity))
        calls = []

        async def upstream(scope, receive, send):
            while (await receive()).get("more_body"):
                pass
            calls.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"id":"synthetic-response"}'})

        async with (
            api.router.lifespan_context(api),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api),
                base_url="https://api.example",
                headers=auth(),
            ) as admin,
            serve(upstream) as url,
        ):
            second = (await admin.post(f"/api/applications/{app_id}/keys", json={})).json()
            third = (await admin.post(f"/api/applications/{app_id}/keys", json={})).json()
            monkeypatch.setenv("PROXYLENS_CPA_URL", url)
            gateways = [
                create_app("gateway", identity_transport=httpx.MockTransport(identity))
                for _ in range(2)
            ]
            async with (
                serve(gateways[0]) as base1,
                serve(gateways[1]) as base2,
                httpx.AsyncClient() as client,
            ):

                async def call(base, credential):
                    return await client.post(
                        base + "/v1/responses",
                        json={"model": "demo"},
                        headers={"Authorization": "Bearer " + credential},
                    )

                responses = await asyncio.gather(
                    call(base1, key["plaintext"]), call(base2, key["plaintext"])
                )
                assert sorted(r.status_code for r in responses) == [200, 429]
                assert (await call(base2, second["plaintext"])).status_code == 200
                assert (await call(base1, third["plaintext"])).status_code == 429
                assert (
                    await admin.post(f"/api/applications/{app_id}/keys/{key['key']['id']}/revoke")
                ).status_code == 200
                assert (await call(base1, key["plaintext"])).status_code == 401
                assert (await call(base2, key["plaintext"])).status_code == 401
                assert (
                    await client.post(base1 + "/v1/chat/completions", json={})
                ).status_code == 404
        assert len(calls) == 2

    asyncio.run(scenario())


def test_application_timeout_bounds_slow_request_upload(environment, monkeypatch, tmp_path):
    routing(monkeypatch, tmp_path)
    monkeypatch.setenv("PROXYLENS_TOTAL_TIMEOUT", "5")

    async def scenario():
        identity = IdentityServer()
        key, _ = await issue(
            identity,
            policy={
                "models": ["demo", "resolved-demo"],
                "providers": ["codex"],
                "timeout_seconds": 1,
            },
        )
        gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
        from urllib.parse import urlsplit

        async with serve(gateway) as base:
            endpoint = urlsplit(base)
            reader, writer = await asyncio.open_connection(endpoint.hostname, endpoint.port)
            writer.write(
                (
                    "POST /v1/responses HTTP/1.1\r\nHost: localhost\r\n"
                    f"Authorization: Bearer {key['plaintext']}\r\n"
                    "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{"
                ).encode()
            )
            await writer.drain()
            try:
                response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
                assert response.startswith(b"HTTP/1.1 504")
            finally:
                writer.close()
                await writer.wait_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["headers", "completion"])
def test_post_dispatch_database_failure_never_replays(environment, monkeypatch, tmp_path, phase):
    routing(monkeypatch, tmp_path)

    async def scenario():
        identity = IdentityServer()
        key, _ = await issue(identity)
        calls = []

        async def upstream(scope, receive, send):
            while (await receive()).get("more_body"):
                pass
            calls.append(scope)
            async with environment.transaction() as conn:
                condition = "headers_at IS NULL" if phase == "headers" else "completed_at IS NULL"
                await conn.execute(
                    "ALTER TABLE gateway_lifecycle ADD CONSTRAINT test_write_failure "
                    f"CHECK ({condition}) NOT VALID"
                )
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"x-cpa-trace-id", TRACE.encode())],
                }
            )
            await send({"type": "http.response.body", "body": b'{"id":"synthetic"}'})

        try:
            async with serve(upstream) as url:
                monkeypatch.setenv("PROXYLENS_CPA_URL", url)
                gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
                async with serve(gateway) as base, httpx.AsyncClient() as client:
                    response = await client.post(
                        base + "/v1/responses",
                        json={"model": "demo"},
                        headers={"Authorization": "Bearer " + key["plaintext"]},
                    )
                    assert response.status_code == (503 if phase == "headers" else 200)
            assert len(calls) == 1
            async with environment.transaction() as conn:
                row = await (await conn.execute("SELECT * FROM gateway_lifecycle")).fetchone()
            if phase == "completion":
                assert row["outcome"] == "pending" and row["completed_at"] is None
                assert gateway.state.gateway.metadata_failures == 1
            else:
                assert row["outcome"] == "storage_error"
        finally:
            async with environment.transaction() as conn:
                await conn.execute(
                    "ALTER TABLE gateway_lifecycle DROP CONSTRAINT IF EXISTS test_write_failure"
                )

    asyncio.run(scenario())


def test_ambiguous_json_model_is_rejected_before_provider(environment, monkeypatch, tmp_path):
    routing(monkeypatch, tmp_path)

    async def scenario():
        identity = IdentityServer()
        key, _ = await issue(identity)
        calls = []

        async def upstream(scope, receive, send):
            calls.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        async with serve(upstream) as url:
            monkeypatch.setenv("PROXYLENS_CPA_URL", url)
            gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
            async with serve(gateway) as base, httpx.AsyncClient() as client:
                response = await client.post(
                    base + "/v1/responses",
                    content=b'{"model":"forbidden","model":"demo"}',
                    headers={
                        "Authorization": "Bearer " + key["plaintext"],
                        "Content-Type": "application/json",
                    },
                )
                assert response.status_code == 400
        assert calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "malformed",
        "unknown",
        "revoked",
        "expired",
        "disabled",
        "deleted-group",
        "nested-group",
        "authority-outage",
        "model",
        "alias-target",
        "alias-name",
        "provider",
        "empty",
        "unverified",
        "body",
        "chunked-body",
        "db-ingress",
    ],
)
def test_denials_never_dispatch(environment, monkeypatch, tmp_path, fault):
    routing(monkeypatch, tmp_path)

    async def scenario():
        identity = IdentityServer()
        key, app_id = await issue(identity)
        calls = []
        policy = {"models": ["demo", "resolved-demo"], "providers": ["codex"]}
        if fault == "alias-target":
            policy["models"] = ["demo"]
        if fault == "alias-name":
            policy["models"] = ["resolved-demo"]
        if fault == "provider":
            policy["providers"] = ["other"]
        if fault == "empty":
            policy = {}
        if fault in {"body", "chunked-body"}:
            policy["max_body_bytes"] = 40
        async with environment.transaction() as conn:
            from psycopg.types.json import Jsonb

            await conn.execute("UPDATE resource_group_refs SET policy = %s", (Jsonb(policy),))
            if fault == "revoked":
                await conn.execute("UPDATE resource_client_keys SET revoked_at = clock_timestamp()")
            if fault == "expired":
                await conn.execute("UPDATE resource_client_keys SET expires_at = clock_timestamp()")
            if fault == "disabled":
                await conn.execute("UPDATE resource_applications SET state = 'disabled'")
        if fault == "deleted-group":
            del identity.groups[G1]
        if fault == "nested-group":
            identity.groups[G1] = 1
        identity.offline = fault == "authority-outage"
        if fault == "unverified":
            path = tmp_path / "routing.json"
            data = json.loads(path.read_text())
            data["demo"]["verified"] = False
            path.write_text(json.dumps(data))

        async def upstream(scope, receive, send):
            calls.append(scope)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        async with serve(upstream) as url:
            monkeypatch.setenv("PROXYLENS_CPA_URL", url)
            gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
            async with serve(gateway) as base, httpx.AsyncClient() as client:
                if fault == "db-ingress":
                    async with environment.transaction() as conn:
                        await conn.execute(
                            "ALTER TABLE gateway_lifecycle ADD CONSTRAINT test_deny "
                            "CHECK (false) NOT VALID"
                        )
                headers = {
                    "Authorization": "Bearer " + key["plaintext"],
                    "Content-Type": "application/json",
                }
                if fault == "missing":
                    del headers["Authorization"]
                elif fault == "malformed":
                    headers["Authorization"] = "Bearer malformed"
                elif fault == "unknown":
                    headers["Authorization"] = "Bearer plk_000000000000_" + "A" * 43
                body = json.dumps(
                    {
                        "model": "unknown" if fault == "model" else "demo",
                        "input": "synthetic-content",
                    }
                ).encode()

                async def chunks():
                    for offset in range(0, len(body), 10):
                        yield body[offset : offset + 10]

                try:
                    response = await client.post(
                        base + "/v1/responses",
                        headers=headers,
                        content=chunks() if fault == "chunked-body" else body,
                    )
                finally:
                    if fault == "db-ingress":
                        async with environment.transaction() as conn:
                            await conn.execute(
                                "ALTER TABLE gateway_lifecycle DROP CONSTRAINT test_deny"
                            )
                expected = (
                    401
                    if fault
                    in {"missing", "malformed", "unknown", "revoked", "expired", "disabled"}
                    else 413
                    if fault in {"body", "chunked-body"}
                    else 503
                    if fault in {"nested-group", "authority-outage", "db-ingress"}
                    else 403
                )
                assert response.status_code == expected, response.text
                assert "synthetic" not in response.text
        assert calls == []
        async with environment.transaction() as conn:
            assert (
                await (await conn.execute("SELECT count(*) AS n FROM lineage_ingress")).fetchone()
            )["n"] == 0
            if fault == "deleted-group":
                row = await (
                    await conn.execute(
                        "SELECT state FROM resource_applications WHERE id = %s", (app_id,)
                    )
                ).fetchone()
                assert row["state"] == "orphaned"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fault",
    [
        "disconnect",
        "disconnect-before-headers",
        "idle",
        "total",
        "headers-timeout",
        "stream-error",
        "http-error",
        "unsafe-id",
        "sse-error",
    ],
)
def test_stream_cleanup_timeouts_and_redacted_errors(environment, monkeypatch, tmp_path, fault):
    routing(monkeypatch, tmp_path)
    monkeypatch.setenv("PROXYLENS_TOTAL_TIMEOUT", "0.5" if fault == "total" else "3")
    monkeypatch.setenv(
        "PROXYLENS_IDLE_TIMEOUT", "0.3" if fault in {"idle", "headers-timeout"} else "2"
    )

    async def scenario():
        identity = IdentityServer()
        key, _ = await issue(identity)
        received = asyncio.Event()
        upstream_closed = asyncio.Event()
        calls = []
        first = (
            b'event: error\ndata: {"type":"error","message":"synthetic-content"}\n\n'
            if fault == "sse-error"
            else b'data: {"type":"response.created"}\n\n'
        )

        async def upstream(scope, receive, send):
            while (await receive()).get("more_body"):
                pass
            calls.append(scope)
            received.set()
            if fault not in {"headers-timeout", "disconnect-before-headers"}:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 429 if fault == "http-error" else 200,
                        "headers": [
                            (b"content-type", b"text/event-stream"),
                            (
                                b"x-cpa-trace-id",
                                b"unsafe-secret" if fault == "unsafe-id" else TRACE.encode(),
                            ),
                        ],
                    }
                )
                if fault == "http-error":
                    await send(
                        {"type": "http.response.body", "body": b"synthetic-secret-error-body"}
                    )
                    return
                await send({"type": "http.response.body", "body": first, "more_body": True})
                if fault == "stream-error":
                    raise RuntimeError("synthetic-secret-error-body")
                if fault in {"unsafe-id", "sse-error"}:
                    await send({"type": "http.response.body", "body": b""})
                    return
            if fault == "total":

                async def heartbeat():
                    while True:
                        await asyncio.sleep(0.05)
                        await send(
                            {"type": "http.response.body", "body": b": ping\n\n", "more_body": True}
                        )

                heart = asyncio.create_task(heartbeat())
            try:
                while (await receive())["type"] != "http.disconnect":
                    pass
                upstream_closed.set()
            finally:
                if fault == "total":
                    heart.cancel()
                    await asyncio.gather(heart, return_exceptions=True)

        async with serve(upstream) as url:
            monkeypatch.setenv("PROXYLENS_CPA_URL", url)
            gateway = create_app("gateway", identity_transport=httpx.MockTransport(identity))
            async with serve(gateway) as base, httpx.AsyncClient(timeout=5) as client:
                headers = {"Authorization": "Bearer " + key["plaintext"]}
                if fault == "disconnect-before-headers":
                    from urllib.parse import urlsplit

                    endpoint = urlsplit(base)
                    reader, writer = await asyncio.open_connection(endpoint.hostname, endpoint.port)
                    body = b'{"model":"demo","stream":true}'
                    writer.write(
                        (
                            "POST /v1/responses HTTP/1.1\r\nHost: localhost\r\n"
                            f"Authorization: {headers['Authorization']}\r\n"
                            "Content-Type: application/json\r\n"
                            f"Content-Length: {len(body)}\r\n\r\n"
                        ).encode()
                        + body
                    )
                    await writer.drain()
                    await asyncio.wait_for(received.wait(), 2)
                    writer.close()
                    await writer.wait_closed()
                else:
                    async with client.stream(
                        "POST",
                        base + "/v1/responses",
                        json={"model": "demo", "stream": True},
                        headers=headers,
                    ) as response:
                        if fault in {"http-error", "headers-timeout"}:
                            assert response.status_code == (429 if fault == "http-error" else 504)
                            assert "synthetic" not in (await response.aread()).decode()
                        else:
                            assert response.status_code == 200
                            chunks = response.aiter_raw()
                            assert await anext(chunks) == first
                            if fault in {"unsafe-id", "sse-error"}:
                                if fault == "unsafe-id":
                                    assert "x-cpa-request-id" not in response.headers
                                assert b"".join([chunk async for chunk in chunks]) == b""
                            elif fault != "disconnect":
                                with pytest.raises(httpx.RemoteProtocolError):
                                    async for _ in chunks:
                                        pass
                if fault in {
                    "disconnect",
                    "disconnect-before-headers",
                    "idle",
                    "total",
                    "headers-timeout",
                }:
                    await asyncio.wait_for(upstream_closed.wait(), 2)
        assert len(calls) == 1
        async with environment.transaction() as conn:
            row = await (await conn.execute("SELECT * FROM gateway_lifecycle")).fetchone()
        expected = (
            "cancelled"
            if fault.startswith("disconnect")
            else "timeout"
            if fault in {"idle", "total", "headers-timeout"}
            else "transport_error"
            if fault == "stream-error"
            else "upstream_error"
            if fault == "http-error"
            else "completed"
        )
        assert row["outcome"] == expected
        assert row["completed_at"] is not None and "synthetic" not in str(row)

    asyncio.run(scenario())
