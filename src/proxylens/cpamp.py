"""Version-pinned, server-side reads of CPAMP durable history (never the CPA queue).

See docs/cpamp-contract.md for HTTP provenance and completeness limitations.
"""

import asyncio
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

CPAMP_VERSION = "v1.14.9"
NORMALIZATION_VERSION = "cpamp-1.14.9/codex-subset-v1"
ANALYTICS_PATH = "/v0/management/monitoring/analytics"
EXPORT_PATH = "/v0/management/usage/export"
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "reasoning_tokens",
    "total_tokens",
    "cache_tokens",
)
METADATA_FIELDS = (
    "auth_index",
    "api_key_hash",
    "source_hash",
    "session_id",
    "parent_session_id",
    "executor_type",
    "reasoning_effort",
    "service_tier",
    "stream",
    "generate",
    "header_trace_id",
    "cache_input_mode",
    "derived_cache_input_mode",
)
KNOWN_OMISSIONS = (
    "sqlite_row_id",
    "execution_id",
    "queue_trace_id",
    "original_queue_json",
    "canonical_token_breakdown",
    "canonical_accounting_quality",
    "stored_normalized_columns",
    "per_record_cost",
)


@dataclass(frozen=True)
class HistoryWindow:
    """Fixed [from_ms, to_ms) interval; each traversal retains identical filters."""

    from_ms: int
    to_ms: int
    providers: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    include_failed: bool = True
    request_id: str | None = None

    def __post_init__(self):
        if not _integer(self.from_ms, 1) or not _integer(self.to_ms, 1):
            raise ValueError("window requires positive integer milliseconds")
        if self.from_ms >= self.to_ms or type(self.include_failed) is not bool:
            raise ValueError("invalid window or filter")
        for values in (self.providers, self.models):
            if (
                not isinstance(values, tuple)
                or len(values) > 100
                or any(not _text(value) or not value for value in values)
            ):
                raise ValueError("filters require bounded tuples of strings")
        if self.request_id is not None and (not _text(self.request_id) or not self.request_id):
            raise ValueError("invalid request identity")

    def payload(self, page_size: int) -> dict[str, Any]:
        filters: dict[str, Any] = {"include_failed": self.include_failed}
        for name in ("providers", "models"):
            if value := getattr(self, name):
                filters[name] = list(value)
        result = {
            "from_ms": self.from_ms,
            "to_ms": self.to_ms,
            "time_zone": "UTC",
            "filters": filters,
            "include": {"events_page": {"limit": page_size}},
        }
        if self.request_id:
            result["search_query"] = self.request_id
        return result


@dataclass(frozen=True)
class NormalizedTokens:
    quality: str
    buckets: dict[str, int] | None = None
    total_tokens: int | None = None
    reason: str | None = None
    version: str = NORMALIZATION_VERSION


@dataclass(frozen=True)
class Cost:
    amount: None = None
    currency: None = None
    classification: str = "unknown"
    pricing_version: None = None


@dataclass(frozen=True)
class UsageRecord:
    instance_id: str
    event_hash: str
    request_id: str | None
    timestamp_ms: int
    provider: str | None
    model: str | None
    requested_model: str | None
    resolved_model: str | None
    response_model: str | None
    failed: bool
    status_code: int | None
    latency_ms: int | None
    ttft_ms: int | None
    raw_tokens: dict[str, Any]
    metadata: dict[str, Any]
    normalized: NormalizedTokens
    source: str
    created_at_ms: int | None = None
    cost: Cost = field(default_factory=Cost)
    cpamp_version: str = CPAMP_VERSION
    known_omissions: tuple[str, ...] = KNOWN_OMISSIONS

    @property
    def identity(self) -> tuple[str, str]:
        return self.instance_id, self.event_hash


@dataclass(frozen=True)
class ReadResult:
    records: tuple[UsageRecord, ...]
    state: str
    traversal_complete: bool
    snapshot_verified: bool = False
    reasons: tuple[str, ...] = ()
    pages: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    generated_at_ms: int | None = None
    coverage: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class AdapterHealth:
    state: str
    last_success_ms: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CollectorStatus:
    state: str
    reasons: tuple[str, ...] = ()
    last_consumed_at_ms: int | None = None
    last_inserted_at_ms: int | None = None
    dead_letters: int | None = None


class _ContractError(Exception):
    """Only fixed, non-sensitive reason codes cross the HTTP boundary."""


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= 2**63 - 1


def _text(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 512 and all(ord(c) >= 32 for c in value)


@dataclass
class _Read:
    records: dict[str, UsageRecord] = field(default_factory=dict)
    conflicts: set[str] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)
    duplicates: int = 0
    rejected: int = 0
    pages: int = 0
    generated_at_ms: int | None = None
    coverage: list[dict[str, Any]] = field(default_factory=list)

    def add(self, row: Any, instance_id: str, source: str, window: HistoryWindow | None):
        try:
            record = _record(row, instance_id, source)
        except _ContractError:
            self.rejected += 1
            self.reasons.add("malformed_record")
            return
        if window and not window.from_ms <= record.timestamp_ms < window.to_ms:
            self.rejected += 1
            self.reasons.add("outside_window")
            return
        if record.event_hash in self.conflicts:
            self.rejected += 1
            return
        if previous := self.records.get(record.event_hash):
            self.duplicates += 1
            self.reasons.add("duplicate_record")
            if previous != record:
                del self.records[record.event_hash]
                self.conflicts.add(record.event_hash)
                self.reasons.add("conflicting_record")
                self.rejected += 2
            return
        if window and window.request_id and record.request_id != window.request_id:
            return  # CPAMP search is substring, not an exact identity predicate.
        if record.normalized.quality != "derived":
            self.reasons.add("normalization_" + record.normalized.quality)
        if not record.request_id:
            self.reasons.add("missing_request_id")
        self.records[record.event_hash] = record

    def result(self, *, complete: bool, unavailable: bool = False) -> ReadResult:
        return ReadResult(
            tuple(self.records.values()),
            "unavailable" if unavailable else "degraded" if self.reasons else "available",
            complete,
            reasons=tuple(sorted(self.reasons)),
            pages=self.pages,
            duplicate_count=self.duplicates,
            rejected_count=self.rejected,
            generated_at_ms=self.generated_at_ms,
            coverage=tuple(self.coverage),
        )


def _coverage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or type(value.get("raw_complete")) is not bool:
        raise _ContractError("schema")
    result = {"raw_complete": value["raw_complete"]}
    for name in ("scope", "mode"):
        if not _text(value.get(name)):
            raise _ContractError("schema")
        result[name] = value[name]
    for name in (
        "raw_event_count",
        "raw_deleted_event_count",
        "min_deleted_timestamp_ms",
        "max_deleted_timestamp_ms",
    ):
        if name in value:
            if not _integer(value[name]):
                raise _ContractError("schema")
            result[name] = value[name]
    return result


def _normalize(
    raw: dict[str, Any],
    provider: str | None,
    source: str,
    row: dict[str, Any],
) -> NormalizedTokens:
    if (
        row.get("provider")
        and row.get("auth_provider_snapshot")
        and (row["provider"] != row["auth_provider_snapshot"])
    ):
        return NormalizedTokens("inconsistent", reason="conflicting_provider")
    if provider != "codex":
        return NormalizedTokens("unknown", reason="unsupported_provider")
    for name in ("cache_input_mode", "derived_cache_input_mode"):
        mode = row.get(name)
        if mode and mode != "included_in_input":
            quality = (
                "inconsistent"
                if mode
                in (
                    "excluded_from_input",
                    "separate_from_input",
                    "read_included_creation_separate",
                )
                else "unknown"
            )
            return NormalizedTokens(quality, reason="unsupported_cache_semantics")
    required = TOKEN_FIELDS[:-1] if source == "cpamp.analytics" else TOKEN_FIELDS
    if any(name not in raw for name in required):
        return NormalizedTokens("unknown", reason="missing_token_fields")
    if any(not _integer(value) for value in raw.values()):
        return NormalizedTokens("inconsistent", reason="invalid_token_counts")
    cache_read = raw["cache_read_tokens"]
    cache_write = raw["cache_creation_tokens"]
    if source == "cpamp.analytics":
        cache_read += raw["cached_tokens"]
    else:
        cache_read += max(
            max(raw["cached_tokens"], raw["cache_tokens"]) - cache_read - cache_write, 0
        )
    buckets = {
        "input_uncached": raw["input_tokens"] - cache_read - cache_write,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output_nonreasoning": raw["output_tokens"] - raw["reasoning_tokens"],
        "reasoning": raw["reasoning_tokens"],
    }
    if min(buckets.values()) < 0 or sum(buckets.values()) != raw["total_tokens"]:
        return NormalizedTokens("inconsistent", reason="token_sum_mismatch")
    return NormalizedTokens("derived", buckets, raw["total_tokens"])


def _record(row: dict[str, Any], instance_id: str, source: str) -> UsageRecord:
    if not isinstance(row, dict) or not isinstance(row.get("event_hash"), str):
        raise _ContractError("malformed_record")
    if not re.fullmatch(r"[0-9a-f]{64}", row["event_hash"]):
        raise _ContractError("malformed_record")
    if not _integer(row.get("timestamp_ms"), 1) or type(row.get("failed")) is not bool:
        raise _ContractError("malformed_record")
    strings = (
        "request_id",
        "model",
        "requested_model",
        "resolved_model",
        "response_model",
        "auth_provider_snapshot",
        "provider",
    ) + METADATA_FIELDS
    for name in strings:
        if name in ("stream", "generate"):
            if name in row and type(row[name]) is not bool:
                raise _ContractError("malformed_record")
        elif name in row and row[name] is not None and not _text(row[name]):
            raise _ContractError("malformed_record")
    for name in ("latency_ms", "ttft_ms", "created_at_ms", "fail_status_code"):
        if row.get(name) is not None and not _integer(row[name]):
            raise _ContractError("malformed_record")
    provider = row.get("auth_provider_snapshot") or row.get("provider") or None
    # Keep numeric surface facts, never arbitrary JSON/string payloads under token keys.
    raw = {
        name: row[name] if type(row[name]) is int else None for name in TOKEN_FIELDS if name in row
    }
    return UsageRecord(
        instance_id=instance_id,
        event_hash=row["event_hash"],
        request_id=row.get("request_id") or None,
        timestamp_ms=row["timestamp_ms"],
        provider=provider,
        model=row.get("model") or None,
        requested_model=row.get("requested_model") or None,
        resolved_model=row.get("resolved_model") or None,
        response_model=row.get("response_model") or None,
        failed=row["failed"],
        status_code=row.get("fail_status_code"),
        latency_ms=row.get("latency_ms"),
        ttft_ms=row.get("ttft_ms"),
        raw_tokens=raw,
        metadata={name: row[name] for name in METADATA_FIELDS if name in row},
        normalized=_normalize(raw, provider, source, row),
        source=source,
        created_at_ms=row.get("created_at_ms"),
    )


class CPAMPAdapter:
    """Owns its HTTP client; use async with. The admin key is never returned."""

    def __init__(
        self,
        base_url: str,
        admin_key: str,
        *,
        instance_id: str,
        page_size: int = 500,
        transport: httpx.AsyncBaseTransport | None = None,
        max_pages: int = 100,
        max_records: int = 50_000,
        max_page_bytes: int = 4 * 1024 * 1024,
        clock_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        stale_after_ms: int = 60_000,
        timeout_seconds: float = 10,
        operation_timeout_seconds: float = 120,
        max_export_bytes: int = 64 * 1024 * 1024,
        max_line_bytes: int = 64 * 1024,
        cpamp_version: str = CPAMP_VERSION,
    ):
        if cpamp_version != CPAMP_VERSION:
            raise ValueError("unsupported CPAMP version")
        url = httpx.URL(base_url)
        if (
            url.scheme not in ("http", "https")
            or not url.host
            or url.userinfo
            or (url.path != "/" or url.query or url.fragment)
        ):
            raise ValueError("CPAMP URL must be an origin without credentials")
        if (
            not _text(instance_id)
            or not instance_id
            or not isinstance(admin_key, str)
            or (not admin_key or not admin_key.isascii() or any(ord(c) <= 32 for c in admin_key))
        ):
            raise ValueError("instance identity and admin key are required")
        if (
            any(
                not _integer(n, 1)
                for n in (
                    page_size,
                    max_pages,
                    max_records,
                    max_page_bytes,
                    max_export_bytes,
                    max_line_bytes,
                    stale_after_ms,
                )
            )
            or page_size > 50_000
        ):
            raise ValueError("limits must be positive; page size cannot exceed 50000")
        if any(
            type(n) not in (float, int) or not math.isfinite(n) or n <= 0
            for n in (
                timeout_seconds,
                operation_timeout_seconds,
            )
        ):
            raise ValueError("timeouts must be positive and finite")
        self.instance_id = instance_id
        self.page_size = page_size
        self.max_pages = max_pages
        self.max_records = max_records
        self.max_page_bytes = max_page_bytes
        self.max_export_bytes = max_export_bytes
        self.max_line_bytes = max_line_bytes
        self._clock = clock_ms
        self.stale_after_ms = stale_after_ms
        self.operation_timeout_seconds = operation_timeout_seconds
        self.last_success: ReadResult | None = None
        self._health = AdapterHealth("unavailable", None, ("not_read",))
        self._collector: CollectorStatus | None = None
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {admin_key}", "Accept-Encoding": "identity"},
            transport=transport,
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    async def read_window(self, window: HistoryWindow) -> ReadResult:
        read = _Read()
        try:
            async with asyncio.timeout(self.operation_timeout_seconds):
                await self._read_window(window, read)
        except (_ContractError, httpx.HTTPError, TimeoutError) as exc:
            read.reasons.add(str(exc) if isinstance(exc, _ContractError) else "transport")
            return self._finish(read.result(complete=False, unavailable=True))
        return self._finish(read.result(complete=True))

    async def read_export(self) -> ReadResult:
        """Stage retained raw rows; EOF cannot certify an atomic projection replacement."""
        read = _Read(reasons={"export_completeness_unverifiable"})
        try:
            async with asyncio.timeout(self.operation_timeout_seconds):
                async with self._client.stream("GET", EXPORT_PATH) as response:
                    self._check_response(response)
                    self._check_length(response, self.max_export_bytes)
                    read.pages = 1
                    pending = bytearray()
                    total = 0
                    rows = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_export_bytes:
                            raise _ContractError("body_limit")
                        pending.extend(chunk)
                        while (end := pending.find(b"\n")) >= 0:
                            if end > self.max_line_bytes:
                                raise _ContractError("line_limit")
                            line = bytes(pending[:end])
                            del pending[: end + 1]
                            rows += 1
                            if rows > self.max_records:
                                raise _ContractError("record_limit")
                            try:
                                row = _json(line)
                            except _ContractError:
                                read.rejected += 1
                                read.reasons.add("malformed_record")
                                continue
                            read.add(row, self.instance_id, "cpamp.export", None)
                        if len(pending) > self.max_line_bytes:
                            raise _ContractError("line_limit")
                    if pending:
                        raise _ContractError("truncated_export")
        except (_ContractError, httpx.HTTPError, TimeoutError) as exc:
            read.reasons.add(str(exc) if isinstance(exc, _ContractError) else "transport")
            return self._finish(read.result(complete=False, unavailable=True))
        return self._finish(read.result(complete=True))

    def health(self, *, expected_pending_since_ms: int | None = None) -> AdapterHealth:
        """Old idle event times alone do not indicate lag; pass oldest expected missing request."""
        health = self._health
        if self._collector and self._collector.state != "available":
            state = (
                "unavailable"
                if "unavailable"
                in (
                    self._collector.state,
                    health.state,
                )
                else "degraded"
            )
            health = replace(health, state=state, reasons=health.reasons + self._collector.reasons)
        if health.state == "unavailable":
            return health
        now = self._clock()
        lag = expected_pending_since_ms is not None and (
            now - expected_pending_since_ms > self.stale_after_ms
        )
        old = health.last_success_ms is not None and (
            now - health.last_success_ms > self.stale_after_ms
        )
        if lag or old:
            reasons = health.reasons + (("reconciliation_lag",) if lag else ("poll_lag",))
            return replace(
                health,
                state="stale" if health.state == "available" else health.state,
                reasons=reasons,
            )
        return health

    async def read_status(self) -> CollectorStatus:
        """Optional collector diagnostics; never refreshes the history-success timestamp."""
        try:
            async with asyncio.timeout(self.operation_timeout_seconds):
                value = _json(await self._body("GET", "/status", self.max_page_bytes))
            collector = value.get("collector") if isinstance(value, dict) else None
            if not isinstance(collector, dict) or not _text(collector.get("collector")):
                raise _ContractError("schema")
            for name in ("lastConsumedAt", "lastInsertedAt", "deadLetters"):
                if not _integer(collector.get(name)):
                    raise _ContractError("schema")
            reasons = []
            if collector["collector"] != "running":
                reasons.append("collector_not_running")
            if collector.get("lastError"):
                reasons.append("collector_error")
            if collector["deadLetters"]:
                reasons.append("dead_letters")
            result = CollectorStatus(
                "degraded" if reasons else "available",
                tuple(reasons),
                collector["lastConsumedAt"],
                collector["lastInsertedAt"],
                collector["deadLetters"],
            )
        except (_ContractError, httpx.HTTPError, TimeoutError) as exc:
            reason = str(exc) if isinstance(exc, _ContractError) else "transport"
            result = CollectorStatus("unavailable", (reason,))
        self._collector = result
        return result

    def _finish(self, result: ReadResult) -> ReadResult:
        last_success_ms = self._health.last_success_ms
        if result.state == "available":
            self.last_success = result
            last_success_ms = self._clock()
        self._health = AdapterHealth(result.state, last_success_ms, result.reasons)
        return result

    async def _body(self, method: str, path: str, limit: int, **kwargs) -> bytes:
        async with self._client.stream(method, path, **kwargs) as response:
            self._check_response(response)
            self._check_length(response, limit)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > limit:
                    raise _ContractError("body_limit")
                body.extend(chunk)
            return bytes(body)

    @staticmethod
    def _check_length(response: httpx.Response, limit: int):
        if (length := response.headers.get("content-length")) is not None:
            if not length.isdecimal():
                raise _ContractError("schema")
            if len(length) > 20 or int(length) > limit:
                raise _ContractError("body_limit")

    @staticmethod
    def _check_response(response: httpx.Response):
        if response.status_code in (401, 403):
            raise _ContractError("authentication")
        if response.status_code >= 400:
            raise _ContractError("upstream_http")
        if response.status_code != 200:
            raise _ContractError("unexpected_http")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise _ContractError("unsupported_encoding")

    async def _read_window(self, window: HistoryWindow, read: _Read):
        payload = window.payload(self.page_size)
        previous_cursor = None
        previous_timestamp = window.to_ms
        first_count = None
        rows_seen = 0
        while True:
            if read.pages >= self.max_pages:
                raise _ContractError("page_limit")
            body = await self._body("POST", ANALYTICS_PATH, self.max_page_bytes, json=payload)
            data = _json(body)
            read.pages += 1
            if not isinstance(data, dict) or not _integer(data.get("generated_at_ms"), 1):
                raise _ContractError("schema")
            if not isinstance(data.get("events"), dict):
                raise _ContractError("schema")
            events = data["events"]
            if (
                not isinstance(events.get("items"), list)
                or type(events.get("has_more")) is not bool
            ):
                raise _ContractError("schema")
            if any(
                not _integer(events.get(name))
                for name in (
                    "total_count",
                    "next_before_ms",
                    "next_before_id",
                )
            ):
                raise _ContractError("schema")
            items = events["items"]
            if len(items) > self.page_size:
                raise _ContractError("page_size_limit")
            rows_seen += len(items)
            if rows_seen > self.max_records:
                raise _ContractError("record_limit")
            if first_count is None:
                first_count = events["total_count"]
            elif first_count != events["total_count"]:
                read.reasons.add("concurrent_history_change")
            cursor = (events["next_before_ms"], events["next_before_id"])
            if events["has_more"]:
                if not items or not window.from_ms <= cursor[0] < window.to_ms or cursor[1] <= 0:
                    raise _ContractError("invalid_cursor")
                if previous_cursor is not None and cursor >= previous_cursor:
                    raise _ContractError("cursor_not_progressing")
                last = items[-1]
                if not isinstance(last, dict) or last.get("timestamp_ms") != cursor[0]:
                    raise _ContractError("invalid_cursor")
            elif cursor != (0, 0):
                raise _ContractError("invalid_cursor")
            for row in items:
                stamp = row.get("timestamp_ms") if isinstance(row, dict) else None
                if _integer(stamp, 1):
                    if stamp > previous_timestamp:
                        raise _ContractError("invalid_order")
                    previous_timestamp = stamp
            read.generated_at_ms = data["generated_at_ms"]
            if "coverage" in data:
                coverage = _coverage(data["coverage"])
                read.coverage.append(coverage)
                if not coverage["raw_complete"] or coverage.get("raw_deleted_event_count", 0):
                    read.reasons.add("retention_gap")
            for row in items:
                read.add(row, self.instance_id, "cpamp.analytics", window)
            if not events["has_more"]:
                if rows_seen != first_count:
                    read.reasons.add("count_mismatch")
                return
            previous_cursor = cursor
            payload["include"]["events_page"].update(
                before_ms=events["next_before_ms"],
                before_id=events["next_before_id"],
            )


def _json(body: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise _ContractError("schema")
            result[key] = value
        return result

    def invalid_constant(_):
        raise _ContractError("schema")

    try:
        return json.loads(body, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _ContractError("schema") from None
