import asyncio
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from proxylens.correlation import CorrelationStatus, IngressRequest, Ownership, UsageIdentity
from proxylens.lineage import LineageRepository, apply_lineage_migration


@pytest.fixture
def lineage_database():
    dsn = os.environ.get("PROXYLENS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set PROXYLENS_TEST_DATABASE_URL to an isolated PostgreSQL database")
    schema = "lineage_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield dsn, schema
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def connect(database):
    dsn, schema = database
    return await psycopg.AsyncConnection.connect(dsn, options=f"-c search_path={schema}")


def test_ingress_owner_and_observation_ids_survive_reconnection(lineage_database):
    async def scenario():
        request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1", "subject1"))
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            await LineageRepository(connection).record_ingress(request)
        async with await connect(lineage_database) as connection:
            assert await LineageRepository(connection).get_ingress(request.request_id) == request

    asyncio.run(scenario())


def test_returned_native_id_links_multiple_retry_records_without_collapsing(lineage_database):
    async def scenario():
        request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
        headers = [("X-CPA-TRACE-ID", "20261024000000-a-019a96c4-0c00-7000-8000-0123456789ab")]
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            repository = LineageRepository(connection)
            await repository.record_ingress(request)
            assert await repository.bind_response(request.request_id, "cpa1", headers) == "partial"
            for event_hash in ("a" * 64, "b" * 64):
                event = UsageIdentity.from_cpamp(
                    "cpamp1", event_hash, "cpa1", "019a96c4-0c00-7000-8000-0123456789ab"
                )
                result = await repository.record_event(event)
                assert result.status == CorrelationStatus.CORRELATED
                assert result.ingress == request
                replay = await repository.record_event(event)
                assert replay.status == CorrelationStatus.DUPLICATE
                assert replay.ingress is None  # no second countable attribution
        async with await connect(lineage_database) as connection:
            repository = LineageRepository(connection)
            for event_hash in ("a" * 64, "b" * 64):
                result = await repository.resolve_event("cpamp1", event_hash)
                assert result.event.event_hash == event_hash
                assert result.ingress == request

    asyncio.run(scenario())


def test_late_native_collision_revokes_earlier_events_after_restart(lineage_database):
    async def scenario():
        first = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
        second = IngressRequest.new(Ownership("issuer", "g2", "app2", "key2"))
        headers = [("X-CPA-TRACE-ID", "20261024000000-a-019a96c4-0c00-7000-8000-0123456789ab")]
        event = UsageIdentity.from_cpamp(
            "cpamp1", "a" * 64, "cpa1", "019a96c4-0c00-7000-8000-0123456789ab"
        )
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            repository = LineageRepository(connection)
            await repository.record_ingress(first)
            await repository.record_ingress(second)
            await repository.bind_response(first.request_id, "cpa1", headers)
            assert (await repository.record_event(event)).ingress == first
        async with await connect(lineage_database) as connection:
            repository = LineageRepository(connection)
            assert await repository.bind_response(second.request_id, "cpa1", headers) == "ambiguous"
        async with await connect(lineage_database) as connection:
            repository = LineageRepository(connection)
            result = await repository.resolve_event("cpamp1", "a" * 64)
            assert (result.status, result.ingress) == (CorrelationStatus.AMBIGUOUS, None)
            assert (await repository.record_event(event)).status == CorrelationStatus.AMBIGUOUS
            assert await repository.get_ingress(first.request_id) == first
            assert await repository.get_ingress(second.request_id) == second

    asyncio.run(scenario())


def test_conflicting_replay_never_reassigns_a_hash_and_stays_ambiguous(lineage_database):
    async def scenario():
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            repository = LineageRepository(connection)
            original = UsageIdentity.from_cpamp(
                "cpamp1", "a" * 64, "cpa1", "019a96c4-0c00-7000-8000-0123456789ab"
            )
            changed = UsageIdentity.from_cpamp(
                "cpamp1", "a" * 64, "cpa2", "019a96c4-0c00-7000-8000-0123456789ac"
            )
            assert (await repository.record_event(original)).status == CorrelationStatus.PARTIAL
            for event in (changed, original, original):
                result = await repository.record_event(event)
                assert result.status == CorrelationStatus.AMBIGUOUS
                assert result.ingress is None
                assert result.event == original

    asyncio.run(scenario())


def test_missing_event_id_cannot_be_repaired_from_owner_or_time(lineage_database):
    async def scenario():
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            repository = LineageRepository(connection)
            request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
            await repository.record_ingress(request)
            assert await repository.bind_response(request.request_id, "cpa1", []) == "missing"
            event = UsageIdentity.from_cpamp("cpamp1", "a" * 64, "cpa1", "Bearer SECRET")
            result = await repository.record_event(event)
            assert (result.status, result.ingress) == (CorrelationStatus.MISSING, None)
            assert "SECRET" not in repr(result)

    asyncio.run(scenario())


def test_concurrent_connections_cannot_hide_collision_or_duplicate_events(lineage_database):
    async def scenario():
        requests = [
            IngressRequest.new(Ownership("issuer", group, app, key))
            for group, app, key in [("g1", "app1", "key1"), ("g2", "app2", "key2")]
        ]
        headers = [("X-CPA-TRACE-ID", "20261024000000-a-019a96c4-0c00-7000-8000-0123456789ab")]
        event = UsageIdentity.from_cpamp(
            "cpamp1", "a" * 64, "cpa1", "019a96c4-0c00-7000-8000-0123456789ab"
        )
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            await apply_lineage_migration(connection)
            repository = LineageRepository(connection)
            for request in requests:
                await repository.record_ingress(request)
        ready = asyncio.Barrier(2)

        async def bind(request):
            async with await connect(lineage_database) as connection:
                await ready.wait()
                await LineageRepository(connection).bind_response(
                    request.request_id, "cpa1", headers
                )

        await asyncio.gather(*(bind(request) for request in requests))

        async def ingest():
            async with await connect(lineage_database) as connection:
                await ready.wait()
                result = await LineageRepository(connection).record_event(event)
                assert result.status == CorrelationStatus.AMBIGUOUS
                assert result.ingress is None

        await asyncio.gather(ingest(), ingest())
        async with await connect(lineage_database) as connection:
            result = await LineageRepository(connection).resolve_event("cpamp1", "a" * 64)
            assert (result.status, result.ingress) == (CorrelationStatus.AMBIGUOUS, None)

    asyncio.run(scenario())


def test_failed_ingress_write_does_not_reassign_committed_ownership(lineage_database):
    async def scenario():
        from dataclasses import replace

        request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            await LineageRepository(connection).record_ingress(request)
        with pytest.raises(psycopg.errors.UniqueViolation):
            async with await connect(lineage_database) as connection:
                await LineageRepository(connection).record_ingress(
                    replace(request, owner=Ownership("issuer", "g2", "app2", "key2"))
                )
        async with await connect(lineage_database) as connection:
            assert await LineageRepository(connection).get_ingress(request.request_id) == request

    asyncio.run(scenario())


def test_late_header_can_complete_partial_history_but_never_missing_history(lineage_database):
    async def scenario():
        request = IngressRequest.new(Ownership("issuer", "g1", "app1", "key1"))
        native = "019a96c4-0c00-7000-8000-0123456789ab"
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            repository = LineageRepository(connection)
            await repository.record_ingress(request)
            await repository.record_event(
                UsageIdentity.from_cpamp("cpamp1", "a" * 64, "cpa1", native)
            )
            await repository.record_event(
                UsageIdentity.from_cpamp("cpamp1", "b" * 64, "cpa1", None)
            )
            await repository.bind_response(
                request.request_id,
                "cpa1",
                [
                    ("X-CPA-TRACE-ID", f"20261024000000-a-{native}"),
                ],
            )
            assert (await repository.resolve_event("cpamp1", "a" * 64)).ingress == request
            assert (await repository.resolve_event("cpamp1", "b" * 64)).status == "missing"

    asyncio.run(scenario())


def test_same_hash_on_different_cpamp_instances_is_not_a_duplicate(lineage_database):
    async def scenario():
        async with await connect(lineage_database) as connection:
            await apply_lineage_migration(connection)
            repository = LineageRepository(connection)
            first = UsageIdentity.from_cpamp("cpamp1", "a" * 64, "cpa1", None)
            second = UsageIdentity.from_cpamp("cpamp2", "a" * 64, "cpa2", None)
            await repository.record_event(first)
            result = await repository.record_event(second)
            assert result.status == CorrelationStatus.MISSING
            assert (await repository.resolve_event("cpamp1", "a" * 64)).event == first
            assert (await repository.resolve_event("cpamp2", "a" * 64)).event == second

    asyncio.run(scenario())
