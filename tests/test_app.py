import asyncio
import socket

import httpx
import pytest

from proxylens.app import create_app


@pytest.mark.parametrize("role", ["api", "gateway", "worker"])
def test_health_distinguishes_live_process_from_unavailable_dependencies(
    role, tmp_path, monkeypatch
):
    password = tmp_path / "password"
    password.write_text("must-never-appear-in-health-response\n")
    monkeypatch.setenv("PROXYLENS_DB_PASSWORD_FILE", str(password))
    # Reserve an unserved local TCP port: no reliance on a particular host service.
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        monkeypatch.setenv("PROXYLENS_DB_HOST", "127.0.0.1")
        monkeypatch.setenv("PROXYLENS_DB_PORT", str(port))
        for name in ("KEYCLOAK", "CPA", "CPAMP"):
            monkeypatch.setenv(f"PROXYLENS_{name}_URL", f"http://127.0.0.1:{port}")

        async def check_health():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=create_app(role)), base_url="http://test"
            ) as client:
                assert (await client.get("/health/live")).status_code == 200
                response = await client.get("/health/ready")
                assert response.status_code == 503
                assert response.json()["dependencies"]["postgres"] == "unavailable"
                assert "must-never-appear" not in response.text
                response = await client.post("/v1/responses", json={"input": "hello"})
                assert response.status_code == (503 if role == "gateway" else 404)
                assert (await client.get("/health/live")).status_code == 200

        asyncio.run(check_health())
