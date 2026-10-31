"""Bounded OTLP v4 HTTP/JSON delivery with explicit pre-admission retries."""

import asyncio
import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from proxylens.exporter import ExportError
from proxylens.exporter_settings import ExporterSettings


@dataclass(frozen=True)
class DeliveryResult:
    state: str
    code: str
    retry_after_seconds: float = 0

    def __post_init__(self):
        import math

        allowed = {
            "ACCEPTED": {"accepted", "accepted_warning"},
            "DEAD_LETTER": {"partial_rejection", "http_rejected", "credentials_unavailable"},
            "UNCERTAIN": {
                "malformed_success",
                "response_limit",
                "transport_uncertain",
                "http_uncertain",
                "unexpected_status",
                "cancelled",
            },
            "RETRY_WAIT": {
                "connect_failed",
                "pool_timeout",
                "throttled",
                "write_timeout_before_send",
                "temporary_http_before_send",
            },
        }
        if self.code not in allowed.get(self.state, set()):
            raise ExportError("invalid_delivery_result")
        if (
            type(self.retry_after_seconds) not in (int, float)
            or not math.isfinite(self.retry_after_seconds)
            or self.retry_after_seconds < 0
        ):
            raise ExportError("invalid_delivery_result")


def _parse_success(body: bytes) -> DeliveryResult:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    def invalid(_):
        raise ValueError()

    try:
        value = json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)
        if not isinstance(value, dict):
            raise ValueError()
        if "partialSuccess" not in value:
            return DeliveryResult("ACCEPTED", "accepted")
        partial = value["partialSuccess"]
        if not isinstance(partial, dict):
            raise ValueError()
        count = partial.get("rejectedSpans", 0)
        if isinstance(count, str) and re.fullmatch(r"[0-9]{1,20}", count):
            count = int(count)
        if type(count) not in (int, float) or count not in (0, 1):
            raise ValueError()
        message = partial.get("errorMessage", "")
        if not isinstance(message, str):
            raise ValueError()
        if count:
            return DeliveryResult("DEAD_LETTER", "partial_rejection")
        return DeliveryResult("ACCEPTED", "accepted_warning" if message else "accepted")
    except (ValueError, UnicodeError, RecursionError):
        return DeliveryResult("UNCERTAIN", "malformed_success")


class OtlpTransport:
    def __init__(self, settings: ExporterSettings, *, transport=None):
        self.settings = settings
        self._transport = transport

    def _credentials(self):
        values = []
        try:
            for path in (self.settings.public_key_file, self.settings.secret_key_file):
                with path.open("rb") as stream:
                    raw = stream.read(4097)
                value = raw.decode("ascii").strip()
                if len(raw) > 4096 or not value or not re.fullmatch(r"[!-9;-~]+", value):
                    raise ValueError()
                values.append(value)
        except (OSError, ValueError, UnicodeError):
            raise ExportError("credentials_unavailable") from None
        return httpx.BasicAuth(*values)

    async def send(self, payload: bytes) -> DeliveryResult:
        if len(payload) > self.settings.max_payload_bytes:
            raise ExportError("payload_limit")
        try:
            auth = self._credentials()
        except ExportError:
            return DeliveryResult("DEAD_LETTER", "credentials_unavailable")
        body_started = False

        class TrackedBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                nonlocal body_started
                body_started = True
                yield payload

            async def aclose(self):
                return None

        try:
            async with asyncio.timeout(self.settings.request_timeout_seconds):
                # No environment proxy, redirects, compression or built-in transport retries.
                async with (
                    httpx.AsyncClient(
                        transport=self._transport,
                        trust_env=False,
                        follow_redirects=False,
                        timeout=self.settings.request_timeout_seconds,
                    ) as client,
                    client.stream(
                        "POST",
                        self.settings.endpoint,
                        content=TrackedBody(),
                        auth=auth,
                        headers={
                            "content-type": "application/json",
                            "x-langfuse-ingestion-version": "4",
                            "accept-encoding": "identity",
                        },
                    ) as response,
                ):
                    if response.status_code == 429:
                        if not self.settings.trusted_pre_admission_429:
                            return DeliveryResult("UNCERTAIN", "http_uncertain")
                        delay = 0
                        header = response.headers.get("retry-after", "")
                        if len(header) <= 128:
                            with suppress(ValueError, TypeError, OverflowError):
                                delay = (
                                    int(header)
                                    if header.isdecimal()
                                    else max(
                                        0,
                                        (
                                            parsedate_to_datetime(header) - datetime.now(UTC)
                                        ).total_seconds(),
                                    )
                                )
                        return DeliveryResult("RETRY_WAIT", "throttled", delay)
                    if response.status_code >= 500 or response.status_code == 408:
                        # Retry only with an explicit destination attestation that
                        # admission did not occur. Bare 408/5xx is ambiguous.
                        if (
                            self.settings.trusted_pre_admission_temporary_failures
                            and response.headers.get("x-proxylens-admission") == "not-admitted"
                        ):
                            return DeliveryResult("RETRY_WAIT", "temporary_http_before_send")
                        return DeliveryResult("UNCERTAIN", "http_uncertain")
                    if 400 <= response.status_code < 500:
                        return DeliveryResult("DEAD_LETTER", "http_rejected")
                    if response.status_code != 200:
                        return DeliveryResult("UNCERTAIN", "unexpected_status")
                    if response.headers.get("content-encoding", "identity") != "identity":
                        return DeliveryResult("UNCERTAIN", "malformed_success")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=1024):
                        if len(body) + len(chunk) > self.settings.max_response_bytes:
                            return DeliveryResult("UNCERTAIN", "response_limit")
                        body.extend(chunk)
                    return _parse_success(bytes(body))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return DeliveryResult("RETRY_WAIT", "connect_failed")
        except httpx.PoolTimeout:
            return DeliveryResult("RETRY_WAIT", "pool_timeout")
        except httpx.WriteTimeout:
            if not body_started:
                return DeliveryResult("RETRY_WAIT", "write_timeout_before_send")
            return DeliveryResult("UNCERTAIN", "transport_uncertain")
        except (httpx.HTTPError, TimeoutError, OSError):
            return DeliveryResult("UNCERTAIN", "transport_uncertain")
