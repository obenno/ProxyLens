"""Responses-only gateway. Bounded ingress, durable authorization, unbuffered egress."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from proxylens.correlation import IngressRequest, Ownership, propagation_headers, returned_cpa_trace
from proxylens.db import Database, StorageUnavailable
from proxylens.lineage import LineageRepository
from proxylens.resources import ResourceError, ResourceRepository

LOG = logging.getLogger(__name__)
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", re.ASCII)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(_):
    raise ValueError("invalid JSON constant")


@dataclass(frozen=True)
class Route:
    model: str
    provider: str


def routing_registry(path: str) -> dict[str, Route]:
    """Operator-attested CPA routing; absence/unverified entries grant nothing."""
    try:
        data = json.loads(Path(path).read_text(), object_pairs_hook=unique_object)
        if not isinstance(data, dict) or len(data) > 500:
            raise ValueError()
        result = {}
        for alias, item in data.items():
            if (
                not NAME.fullmatch(alias)
                or not isinstance(item, dict)
                or set(item) != {"model", "provider", "verified"}
                or not all(
                    isinstance(item[k], str) and NAME.fullmatch(item[k])
                    for k in ("model", "provider")
                )
                or type(item["verified"]) is not bool
            ):
                raise ValueError()
            if item["verified"]:
                result[alias] = Route(item["model"], item["provider"])
        return result
    except (OSError, ValueError, TypeError):
        raise ValueError("invalid gateway routing registry") from None


@dataclass(frozen=True)
class GatewaySettings:
    registry_file: str = "deploy/gateway/routes.json"
    credential_file: str = "/run/secrets/cpa_client_key"
    cpa_instance_id: str = "primary"
    max_body_bytes: int = 4 * 1024 * 1024
    total_timeout: float = 120
    idle_timeout: float = 30

    def __post_init__(self):
        if (
            not NAME.fullmatch(self.cpa_instance_id)
            or not 1 <= self.max_body_bytes <= 64 * 1024 * 1024
            or not 0 < self.total_timeout <= 600
            or not 0 < self.idle_timeout <= 120
        ):
            raise ValueError("invalid gateway limits")


class Gateway:
    def __init__(
        self,
        database: Database,
        resources: ResourceRepository,
        client: httpx.AsyncClient,
        settings: GatewaySettings,
        *,
        issuer: str,
        cpa_url: str,
    ):
        url = urlsplit(cpa_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path
        ):
            raise ValueError("invalid CPA endpoint")
        self.database, self.resources, self.client = database, resources, client
        self.settings, self.issuer, self.cpa_url = settings, issuer, cpa_url
        self.routes = routing_registry(settings.registry_file)
        try:
            self.credential = Path(settings.credential_file).read_text().strip()
            if (
                not self.credential
                or not self.credential.isascii()
                or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in self.credential)
            ):
                raise ValueError()
        except (OSError, ValueError):
            raise ValueError("invalid CPA client credential file") from None
        self.metadata_failures = 0

    async def prepare(self, request: Request):
        started = asyncio.get_running_loop().time()
        async with asyncio.timeout(self.settings.total_timeout) as budget:
            credentials = request.headers.getlist("authorization")
            if len(credentials) != 1 or not credentials[0].startswith("Bearer "):
                raise ResourceError("invalid_client_key", 401)
            key = credentials[0][7:]
            identity = await self.resources.resolve_key(key)
            request.state.gateway_denial = {
                "actor": None,
                "group_id": identity.group_id,
                "resource_id": identity.application_id,
            }
            if (
                request.headers.get("content-type", "").split(";", 1)[0].strip()
                != "application/json"
            ):
                raise ResourceError("json_required", 415)
            if request.headers.get("content-encoding", "identity") != "identity":
                raise ResourceError("unsupported_encoding", 415)
            policy = await self.resources.effective_policy(identity.application_id)
            deadline = started + min(
                self.settings.total_timeout, policy.timeout_seconds or self.settings.total_timeout
            )
            budget.reschedule(deadline)
            ceiling = min(
                self.settings.max_body_bytes, policy.max_body_bytes or self.settings.max_body_bytes
            )
            length = request.headers.get("content-length")
            if length is not None:
                if not length.isdecimal():
                    raise ResourceError("invalid_body", 400)
                if int(length) > ceiling:
                    raise ResourceError("body_too_large", 413)
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > ceiling:
                    raise ResourceError("body_too_large", 413)
                body.extend(chunk)
            try:
                payload = json.loads(
                    body.decode("utf-8"),
                    parse_constant=invalid_constant,
                    object_pairs_hook=unique_object,
                )
                if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
                    raise ValueError()
                if "stream" in payload and type(payload["stream"]) is not bool:
                    raise ValueError()
                model = payload["model"]
            except (ValueError, UnicodeError, RecursionError):
                raise ResourceError("invalid_body", 400) from None
            route = self.routes.get(model)
            if route is None:
                raise ResourceError("routing_unverified", 403)
            group = await self.resources.group_lookup(identity.group_id)
            if group is None:
                await self.resources.reconcile_group(identity.group_id, actor="gateway")
                raise ResourceError("group_unusable", 403)
            authorization = await self.resources.authorize(
                key,
                model=route.model,
                requested_model=model,
                provider=route.provider,
                body_bytes=len(body),
            )
            owner = authorization.identity
            ingress = IngressRequest.new(
                Ownership(self.issuer, owner.group_id, owner.application_id, owner.key_id)
            )
            policy = authorization.policy
            deadline = min(
                deadline, started + (policy.timeout_seconds or self.settings.total_timeout)
            )
            budget.reschedule(deadline)
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError()
            async with self.database.transaction() as conn:
                await LineageRepository(conn).record_ingress(ingress)
                await conn.execute(
                    "INSERT INTO gateway_lifecycle(request_id, requested_model, routing_model, "
                    "routing_provider, group_policy_version, application_policy_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        ingress.request_id,
                        model,
                        route.model,
                        route.provider,
                        policy.group_version,
                        policy.application_version,
                    ),
                )
            return ForwardResponse(self, ingress, bytes(body), started, deadline)


class ForwardResponse(Response):
    """Own the socket lifecycle, including disconnects while waiting for headers."""

    def __init__(self, gateway, ingress, body, started, deadline):
        super().__init__()
        self.gateway, self.ingress, self.body = gateway, ingress, body
        self.started, self.deadline = started, deadline
        self.headers_sent = False
        self.outcome = "pending"
        self.http_status = None
        self.first_byte_at = None
        self.response_bytes = 0

    async def _forward(self, send):
        g = self.gateway
        async with asyncio.timeout_at(self.deadline):
            headers = {
                **propagation_headers(self.ingress),
                "Authorization": "Bearer " + g.credential,
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
            }
            async with g.client.stream(
                "POST", g.cpa_url + "/v1/responses", content=self.body, headers=headers
            ) as upstream:
                self.http_status = upstream.status_code
                returned = upstream.headers.multi_items()
                async with g.database.transaction() as conn:
                    await LineageRepository(conn).bind_response(
                        self.ingress.request_id, g.settings.cpa_instance_id, returned
                    )
                    await conn.execute(
                        "UPDATE gateway_lifecycle SET headers_at = clock_timestamp(), "
                        "http_status = %s "
                        "WHERE request_id = %s",
                        (self.http_status, self.ingress.request_id),
                    )
                safe = {
                    "X-Request-ID": str(self.ingress.request_id),
                    "Cache-Control": "no-store",
                    "X-Accel-Buffering": "no",
                }
                trace = returned_cpa_trace(returned)
                if trace is not None:
                    safe["X-CPA-Request-ID"] = str(trace.request_id)
                if upstream.status_code >= 300:
                    self.outcome = "upstream_error"
                    status = upstream.status_code if upstream.status_code >= 400 else 502
                    response = JSONResponse(
                        {"error": "upstream_error"}, status_code=status, headers=safe
                    )
                    self.headers_sent = True
                    await response({"type": "http"}, None, send)
                    return
                content_type = upstream.headers.get("content-type", "").split(";", 1)[0]
                safe["Content-Type"] = (
                    "text/event-stream"
                    if content_type == "text/event-stream"
                    else "application/json"
                )
                encoding = upstream.headers.get("content-encoding")
                if encoding:
                    if encoding not in {"gzip", "br", "deflate", "identity"}:
                        raise httpx.RemoteProtocolError("unsupported response encoding")
                    safe["Content-Encoding"] = encoding
                await send(
                    {
                        "type": "http.response.start",
                        "status": upstream.status_code,
                        "headers": [(k.lower().encode(), v.encode()) for k, v in safe.items()],
                    }
                )
                self.headers_sent = True
                async for chunk in upstream.aiter_raw():
                    if self.first_byte_at is None:
                        self.first_byte_at = datetime.now(UTC)
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
                    self.response_bytes += len(chunk)
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                self.outcome = "completed"

    async def _finish(self):
        try:
            async with asyncio.timeout(3), self.gateway.database.transaction() as conn:
                await conn.execute(
                    "UPDATE gateway_lifecycle SET completed_at = clock_timestamp(), outcome = %s, "
                    "http_status = %s, duration_ms = %s, first_byte_at = %s, response_bytes = %s "
                    "WHERE request_id = %s AND completed_at IS NULL",
                    (
                        self.outcome,
                        self.http_status,
                        max(0, int((asyncio.get_running_loop().time() - self.started) * 1000)),
                        self.first_byte_at,
                        self.response_bytes,
                        self.ingress.request_id,
                    ),
                )
        except (StorageUnavailable, TimeoutError):
            self.gateway.metadata_failures += 1
            LOG.error("gateway_completion_unavailable request_id=%s", self.ingress.request_id)

    async def __call__(self, scope, receive, send):
        async def disconnected():
            while (await receive())["type"] != "http.disconnect":
                pass

        forward = asyncio.create_task(self._forward(send))
        disconnect = asyncio.create_task(disconnected())
        failure = None
        try:
            done, _ = await asyncio.wait((forward, disconnect), return_when=asyncio.FIRST_COMPLETED)
            if forward in done:
                await forward
            else:
                self.outcome = "cancelled"
        except (TimeoutError, httpx.TimeoutException):
            self.outcome, failure = "timeout", (504, "upstream_timeout")
        except StorageUnavailable:
            self.outcome, failure = "storage_error", (503, "storage_unavailable")
        except (httpx.HTTPError, OSError):
            self.outcome, failure = "transport_error", (502, "upstream_unavailable")
        except asyncio.CancelledError:
            self.outcome = "cancelled"
            raise
        except Exception:
            self.outcome, failure = "internal_error", (500, "internal_error")
        finally:
            forward.cancel()
            disconnect.cancel()
            await asyncio.gather(forward, disconnect, return_exceptions=True)
            await asyncio.shield(self._finish())
        if failure:
            if self.headers_sent:
                # No synthetic SSE event, retry, or successful terminator on a partial stream.
                raise RuntimeError("gateway_stream_terminated") from None
            status, code = failure
            await JSONResponse(
                {"error": code},
                status_code=status,
                headers={"X-Request-ID": str(self.ingress.request_id), "Cache-Control": "no-store"},
            )(scope, receive, send)


def install_gateway_routes(app: FastAPI):
    @app.post("/v1/responses")
    async def responses(request: Request):
        try:
            gateway = getattr(app.state, "gateway", None)
            if gateway is None:
                raise ResourceError("gateway_unavailable", 503)
            return await gateway.prepare(request)
        except ResourceError as error:
            status, code = error.status, error.code
            gateway = getattr(app.state, "gateway", None)
            if gateway is not None and status in {401, 403, 409, 429}:
                context = getattr(request.state, "gateway_denial", {})
                try:
                    await gateway.resources.record_denial(
                        "authorization.denied",
                        actor=context.get("actor"),
                        group_id=context.get("group_id"),
                        resource_id=context.get("resource_id"),
                        code=code,
                    )
                except StorageUnavailable:
                    status, code = 503, "storage_unavailable"
        except StorageUnavailable:
            status, code = 503, "storage_unavailable"
        except TimeoutError:
            status, code = 504, "request_timeout"
        except ClientDisconnect:
            status, code = 400, "client_disconnected"
        except Exception:
            status, code = 503, "authorization_unavailable"
        return JSONResponse(
            {"error": code}, status_code=status, headers={"Cache-Control": "no-store"}
        )
