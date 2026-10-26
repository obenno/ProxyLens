import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from proxylens.cpamp import CPAMPAdapter, HistoryWindow

FIXTURES = Path(__file__).parent / "fixtures" / "cpamp-v1.14.9"
STAMP = 1792800000000
HASHES = (
    "aa2f4fa70b74a4b8851e3247959596141665da2a6bb16b4d52db4fc81653a707",
    "8a83d94d44b74afe4f81305048bf6e5b3f5f5ba22a2947652fdcf5b83290fc8c",
    "dae67da4e16569a875626fbcd81c26b389173bf687059bf27cdd67e8e1dc5081",
)


def page(index=0, *, last=True):
    result = json.loads((FIXTURES / "analytics.json").read_text())
    row = result["events"]["items"][0]
    row["event_hash"] = HASHES[index]
    if index:
        row["request_id"] = "019a96c4-0c00-7000-8000-0123456789ab"
    if index == 2:
        row.update(failed=True, fail_status_code=503)
    result["events"].update(
        next_before_ms=0 if last else STAMP,
        next_before_id=0 if last else 3 - index,
        has_more=not last,
        total_count=1 if last and index == 0 else 3,
    )
    return result


def test_equal_timestamp_pages_preserve_attempts_and_surface_provenance():
    requests = []

    def respond(request):
        assert request.method == "POST"
        assert request.url.path == "/v0/management/monitoring/analytics"
        assert request.headers["authorization"] == "Bearer test-admin"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=page(len(requests) - 1, last=len(requests) == 3))

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "test-admin",
            instance_id="cpamp-local",
            transport=httpx.MockTransport(respond),
            page_size=1,
        ) as adapter:
            result = await adapter.read_window(
                HistoryWindow(
                    STAMP,
                    STAMP + 1000,
                    providers=("codex",),
                    models=("model-demo",),
                )
            )
            assert result.state == "available"
            assert result.traversal_complete
            assert not result.snapshot_verified
            assert [r.identity for r in result.records] == [("cpamp-local", h) for h in HASHES]
            assert result.records[1].request_id == result.records[2].request_id
            record = result.records[0]
            assert record.source == "cpamp.analytics"
            assert record.cpamp_version == "v1.14.9"
            assert record.raw_tokens["cached_tokens"] == 0
            assert record.normalized.quality == "derived"
            assert record.normalized.buckets == {
                "input_uncached": 80,
                "cache_read": 20,
                "cache_write": 0,
                "output_nonreasoning": 30,
                "reasoning": 10,
            }
            assert record.normalized.total_tokens == 140
            assert record.cost.amount is None
            assert record.cost.classification == "unknown"
            assert record.requested_model == "model-demo"
            assert record.resolved_model == "gpt-demo"
            assert result.records[2].failed is True
            assert result.records[2].status_code == 503
            assert record.latency_ms == 500
            assert "canonical_token_breakdown" in record.known_omissions

    asyncio.run(exercise())
    assert len(requests) == 3
    for request in requests:
        assert request["from_ms"] == STAMP
        assert request["to_ms"] == STAMP + 1000
        assert request["filters"] == {
            "providers": ["codex"],
            "models": ["model-demo"],
            "include_failed": True,
        }
    assert requests[0]["include"] == {"events_page": {"limit": 1}}
    assert requests[1]["include"] == {
        "events_page": {"limit": 1, "before_ms": STAMP, "before_id": 3}
    }
    assert requests[2]["include"]["events_page"]["before_id"] == 2


@pytest.mark.parametrize(
    "failure, reason",
    [
        ("auth", "authentication"),
        ("outage", "upstream_http"),
        ("redirect", "unexpected_http"),
        ("timeout", "transport"),
        ("json", "schema"),
        ("envelope", "schema"),
        ("body", "body_limit"),
        ("page_size", "page_size_limit"),
        ("cursor", "cursor_not_progressing"),
        ("empty_more", "invalid_cursor"),
        ("pages", "page_limit"),
        ("records", "record_limit"),
    ],
)
def test_failures_are_bounded_redacted_and_preserve_last_success(failure, reason):
    clock = [1000]
    failing = [False]
    calls = []

    def respond(request):
        calls.append(request)
        if not failing[0]:
            return httpx.Response(200, json=page())
        if failure in ("auth", "outage", "redirect"):
            status = {"auth": 401, "outage": 503, "redirect": 302}[failure]
            return httpx.Response(status, text="secret-sentinel", headers={"location": "/secret"})
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-sentinel")
        if failure == "json":
            return httpx.Response(200, content=b"secret-sentinel")
        if failure == "envelope":
            return httpx.Response(200, json={"events": {"items": []}})
        if failure == "body":
            return httpx.Response(200, content=b"x" * 10001)
        data = page(last=False)
        if failure == "empty_more":
            data["events"]["items"] = []
        if failure == "page_size":
            data["events"]["items"] *= 2
        if failure == "records":
            payload = json.loads(request.content)
            if "before_id" in payload["include"]["events_page"]:
                data = page(1)
        return httpx.Response(200, json=data)

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "secret-sentinel",
            instance_id="one",
            page_size=1,
            transport=httpx.MockTransport(respond),
            clock_ms=lambda: clock[0],
            max_page_bytes=10000,
            max_pages=1 if failure == "pages" else 3,
            max_records=1 if failure == "records" else 10,
        ) as adapter:
            good = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert adapter.health().state == "available"
            clock[0] += 60_001
            assert adapter.health().state == "stale"
            failing[0] = True
            result = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert result.state == "unavailable"
            assert not result.traversal_complete
            assert reason in result.reasons
            assert "secret-sentinel" not in repr(result)
            assert adapter.last_success == good
            assert adapter.health().last_success_ms == 1000
            assert adapter.health().state == "unavailable"
            assert len(calls) <= 4
            assert all(r.url.path == "/v0/management/monitoring/analytics" for r in calls)
            failing[0] = False
            await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert adapter.health().state == "available"
            assert adapter.health(expected_pending_since_ms=1000).state == "stale"

    asyncio.run(exercise())


def test_read_preserves_good_rows_reports_retention_bad_rows_and_duplicate_reads():
    data = page()
    row = data["events"]["items"][0]
    row.update(
        {
            "api_key": "secret-sentinel",
            "raw_json": "secret-sentinel",
            "response_metadata": {"secret": "secret-sentinel"},
            "client_ip": "secret-sentinel",
            "access_token_sha256": "secret-sentinel",
            "fail_summary": "secret-sentinel",
            "account_snapshot": "secret-sentinel",
            "tokens": {"secret": "secret-sentinel"},
        }
    )
    data["events"]["items"] += [copy.deepcopy(row), {"event_hash": "bad"}]
    data["events"]["total_count"] = 3
    data["coverage"] = {
        "scope": "primary",
        "mode": "mixed",
        "raw_complete": False,
        "core_aggregate_used": True,
        "raw_event_count": 3,
        "raw_deleted_event_count": 2,
        "min_deleted_timestamp_ms": STAMP,
        "max_deleted_timestamp_ms": STAMP,
        "fidelity_limitations": ["event_details_require_raw_events"],
        "unexpected": "secret-sentinel",
    }

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "secret-sentinel",
            instance_id="one",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
        ) as adapter:
            result = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert result.state == "degraded"
            assert result.traversal_complete
            assert len(result.records) == 1
            assert result.duplicate_count == 1
            assert result.rejected_count == 1
            assert set(result.reasons) >= {"retention_gap", "malformed_record", "duplicate_record"}
            assert result.coverage[0]["raw_deleted_event_count"] == 2
            assert "secret-sentinel" not in repr(result)
            # Overlapping reads retain stable identity; persistent dedup belongs to the projection.
            repeated = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert repeated.records[0].identity == result.records[0].identity

    asyncio.run(exercise())


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data, fail=False):
        self.data = data
        self.fail = fail
        self.closed = False

    async def __aiter__(self):
        for offset in range(0, len(self.data), 37):
            yield self.data[offset : offset + 37]
        if self.fail:
            raise httpx.ReadError("secret-sentinel")

    async def aclose(self):
        self.closed = True


def test_export_is_bounded_snapshot_candidate_with_distinct_raw_token_semantics():
    stream = Chunks((FIXTURES / "export.jsonl").read_bytes())

    def respond(request):
        assert request.method == "GET"
        assert request.url.path == "/v0/management/usage/export"
        assert not request.url.query
        return httpx.Response(200, stream=stream, headers={"content-type": "application/x-ndjson"})

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(respond),
        ) as adapter:
            result = await adapter.read_export()
            assert result.state == "degraded"
            assert result.traversal_complete
            assert not result.snapshot_verified
            assert "export_completeness_unverifiable" in result.reasons
            assert len(result.records) == 3
            record = result.records[0]
            assert record.identity == ("one", HASHES[2])
            assert record.source == "cpamp.export"
            assert record.raw_tokens["cached_tokens"] == 20
            assert record.raw_tokens["cache_read_tokens"] == 20
            assert record.normalized.buckets == {
                "input_uncached": 80,
                "cache_read": 20,
                "cache_write": 0,
                "output_nonreasoning": 30,
                "reasoning": 10,
            }
            assert record.created_at_ms == 1792772909329
            assert record.metadata["derived_cache_input_mode"] == "included_in_input"
            assert stream.closed

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "scenario, reason, complete",
    [
        ("truncated", "truncated_export", False),
        ("broken", "transport", False),
        ("body", "body_limit", False),
        ("line", "line_limit", False),
        ("records", "record_limit", False),
        ("malformed", "malformed_record", True),
        ("duplicates", "duplicate_record", True),
    ],
)
def test_export_failure_never_claims_a_complete_rebuild(scenario, reason, complete):
    data = (FIXTURES / "export.jsonl").read_bytes()
    if scenario == "truncated":
        data = data[:-10]
    if scenario == "malformed":
        data += b'{"event_hash":"secret-sentinel"}\n'
    if scenario == "duplicates":
        data += data
    stream = Chunks(data, fail=scenario == "broken")

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
            max_export_bytes=100 if scenario == "body" else 100_000,
            max_line_bytes=100 if scenario == "line" else 10_000,
            max_records=2 if scenario == "records" else 100,
        ) as adapter:
            result = await adapter.read_export()
            assert result.traversal_complete == complete
            assert result.state == ("degraded" if complete else "unavailable")
            assert reason in result.reasons
            assert not result.snapshot_verified
            assert "secret-sentinel" not in repr(result)
            assert stream.closed

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "changes, removed, quality",
    [
        ({}, ("cache_creation_tokens",), "unknown"),
        ({"input_tokens": None}, (), "inconsistent"),
        ({"input_tokens": True}, (), "inconsistent"),
        ({"input_tokens": -1}, (), "inconsistent"),
        ({"input_tokens": "secret-sentinel"}, (), "inconsistent"),
        ({"total_tokens": 150}, (), "inconsistent"),
        ({"reasoning_tokens": 41}, (), "inconsistent"),
        ({"cache_read_tokens": 101}, (), "inconsistent"),
        ({"auth_provider_snapshot": "other"}, (), "unknown"),
        ({"input_tokens": 2**63, "total_tokens": 2**63 + 40}, (), "inconsistent"),
        ({"cache_input_mode": "excluded_from_input"}, (), "inconsistent"),
        ({"cache_input_mode": "separate_from_input"}, (), "inconsistent"),
        ({"derived_cache_input_mode": "read_included_creation_separate"}, (), "inconsistent"),
        ({"cache_input_mode": "future-mode"}, (), "unknown"),
        ({"provider": "other"}, (), "inconsistent"),
    ],
)
def test_uncertain_tokens_remain_unknown_not_zero(changes, removed, quality):
    data = page()
    row = data["events"]["items"][0]
    row.update(changes)
    for name in removed:
        del row[name]

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
        ) as adapter:
            result = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert result.state == "degraded"
            record = result.records[0]
            assert record.normalized.quality == quality
            assert record.normalized.buckets is None
            assert record.normalized.total_tokens is None
            assert record.cost.amount is None
            assert "secret-sentinel" not in repr(result)

    asyncio.run(exercise())


def test_legacy_cache_residual_and_exact_request_search_do_not_double_count():
    data = page()
    row = data["events"]["items"][0]
    row["cached_tokens"] = 5
    wanted = row["request_id"]
    near_match = copy.deepcopy(row)
    near_match.update(event_hash=HASHES[1], request_id=wanted + "-suffix")
    data["events"]["items"].append(near_match)
    data["events"]["total_count"] = 2

    def respond(request):
        assert json.loads(request.content)["search_query"] == wanted
        return httpx.Response(200, json=data)

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(respond),
        ) as adapter:
            result = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1, request_id=wanted))
            assert len(result.records) == 1
            assert result.records[0].normalized.buckets == {
                "input_uncached": 75,
                "cache_read": 25,
                "cache_write": 0,
                "output_nonreasoning": 30,
                "reasoning": 10,
            }

    asyncio.run(exercise())


def test_conflicting_duplicate_is_quarantined_and_missing_request_id_is_explicit():
    data = page()
    row = data["events"]["items"][0]
    conflict = copy.deepcopy(row)
    conflict["request_id"] = "a-different-owner"
    missing = copy.deepcopy(row)
    missing["event_hash"] = HASHES[1]
    del missing["request_id"]
    data["events"]["items"] = [row, conflict, missing]
    data["events"]["total_count"] = 3

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data)),
        ) as adapter:
            result = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert result.state == "degraded"
            assert len(result.records) == 1
            assert result.records[0].request_id is None
            assert result.rejected_count == 2
            assert {"conflicting_record", "missing_request_id"} <= set(result.reasons)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page_size": 0},
        {"page_size": 50001},
        {"max_pages": -1},
        {"max_records": 0},
        {"max_page_bytes": 0},
        {"max_export_bytes": 0},
        {"max_line_bytes": 0},
        {"timeout_seconds": 0},
        {"operation_timeout_seconds": float("inf")},
        {"cpamp_version": "v2.0.0"},
        {"base_url": "http://key@cpamp.test"},
        {"base_url": "http://cpamp.test/other"},
        {"base_url": "http://cpamp.test/?x=secret"},
        {"admin_key": ""},
        {"instance_id": ""},
    ],
)
def test_invalid_configuration_rejected_before_http(kwargs):
    config = {"base_url": "http://cpamp.test", "admin_key": "key", "instance_id": "one"}
    config.update(kwargs)
    with pytest.raises(ValueError):
        CPAMPAdapter(**config)


@pytest.mark.parametrize(
    "args, kwargs",
    [
        ((0, 1), {}),
        ((1, 1), {}),
        ((True, 1000), {}),
        ((1000, 1), {}),
        ((1, 1000), {"providers": ["codex"]}),
        ((1, 1000), {"include_failed": "false"}),
        ((1, 1000), {"request_id": ""}),
    ],
)
def test_windows_and_filters_are_immutable_validated_inputs(args, kwargs):
    with pytest.raises(ValueError):
        HistoryWindow(*args, **kwargs)


def test_collector_diagnostics_distinguish_idle_from_stopped_error_and_loss():
    collector = {
        "collector": "running",
        "upstream": "secret-sentinel",
        "lastConsumedAt": 0,
        "lastInsertedAt": 0,
        "totalInserted": 0,
        "totalSkipped": 0,
        "deadLetters": 0,
    }
    fail_status = [False]

    def respond(request):
        if request.url.path == "/status":
            if fail_status[0]:
                return httpx.Response(503, text="secret-sentinel")
            return httpx.Response(200, json={"collector": collector, "dbPath": "secret-sentinel"})
        return httpx.Response(200, json=page())

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(respond),
        ) as adapter:
            await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            idle = await adapter.read_status()
            assert idle.state == "available"
            assert idle.last_inserted_at_ms == 0
            collector.update(collector="stopped", lastError="secret-sentinel", deadLetters=2)
            status = await adapter.read_status()
            assert status.state == "degraded"
            assert status.dead_letters == 2
            assert set(status.reasons) == {
                "collector_not_running",
                "collector_error",
                "dead_letters",
            }
            assert adapter.health().state == "degraded"
            assert "secret-sentinel" not in repr(status)
            fail_status[0] = True
            assert (await adapter.read_status()).state == "unavailable"
            assert adapter.health().state == "unavailable"
            assert adapter.last_success is not None

    asyncio.run(exercise())


def test_degraded_read_does_not_replace_last_clean_history():
    responses = [page(), page()]
    responses[1]["events"]["items"] = [{"event_hash": "broken"}]

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=responses.pop(0))),
        ) as adapter:
            clean = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            degraded = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert degraded.state == "degraded"
            assert adapter.last_success == clean

    asyncio.run(exercise())


def test_ambiguous_json_envelope_is_not_accepted_as_success():
    body = json.dumps(page()).replace('"has_more": false', '"has_more": true, "has_more": false')

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)),
        ) as adapter:
            result = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
            assert result.state == "unavailable"
            assert result.reasons == ("schema",)

    asyncio.run(exercise())


def test_declared_size_and_compressed_responses_fail_before_stream_consumption():
    async def exercise():
        for headers, reason in (
            ({"content-length": "10001"}, "body_limit"),
            ({"content-encoding": "gzip"}, "unsupported_encoding"),
        ):
            stream = Chunks(b"unread")
            async with CPAMPAdapter(
                "http://cpamp.test",
                "key",
                instance_id="one",
                max_page_bytes=10_000,
                transport=httpx.MockTransport(
                    lambda _, h=headers, s=stream: httpx.Response(200, headers=h, stream=s)
                ),
            ) as adapter:
                result = await adapter.read_window(HistoryWindow(STAMP, STAMP + 1))
                assert result.state == "unavailable"
                assert reason in result.reasons
                assert stream.closed

    asyncio.run(exercise())


def test_whole_operation_deadline_closes_a_stalled_stream():
    class Stalled(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b"{"
            await asyncio.Future()

        async def aclose(self):
            self.closed = True

    stream = Stalled()

    async def exercise():
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            operation_timeout_seconds=0.01,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
        ) as adapter:
            result = await adapter.read_export()
            assert result.state == "unavailable" and not result.traversal_complete
            assert "transport" in result.reasons
            assert stream.closed

    asyncio.run(exercise())


def test_caller_cancellation_propagates_and_closes_http_stream():
    async def exercise():
        started = asyncio.Event()

        class Stalled(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                started.set()
                yield b"{"
                await asyncio.Future()

            async def aclose(self):
                self.closed = True

        stream = Stalled()
        async with CPAMPAdapter(
            "http://cpamp.test",
            "key",
            instance_id="one",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream)),
        ) as adapter:
            task = asyncio.create_task(adapter.read_window(HistoryWindow(STAMP, STAMP + 1)))
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.closed
            assert adapter.last_success is None

    asyncio.run(exercise())
