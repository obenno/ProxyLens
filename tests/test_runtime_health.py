import asyncio
from datetime import UTC, datetime

from proxylens.app import worker_operations_ready
from proxylens.cpamp import AdapterHealth, CollectorStatus, ReadResult
from proxylens.db import StorageUnavailable
from proxylens.operations_health import ExportHealth, ProjectionHealth, operations_health
from proxylens.runtime import OperationsSupervisor


class FakeAdapter:
    def __init__(self, history):
        self.history = history
        self.last_success = None
        self.status_calls = 0

    async def read_window(self, _window):
        if self.history.state == "available":
            self.last_success = self.history
        return self.history

    async def read_status(self):
        self.status_calls += 1
        return CollectorStatus("available")

    def health(self):
        return AdapterHealth(
            "available" if self.last_success is not None else "unavailable",
            1 if self.last_success is not None else None,
            (),
        )


class ClockedAdapter:
    def __init__(self, results, clock):
        self.results = list(results)
        self.clock = clock
        self.history_calls = 0
        self.last_success_ms = None
        self.state = "unavailable"
        self.status_calls = 0

    async def read_window(self, _window):
        self.history_calls += 1
        result = self.results.pop(0)
        self.state = result.state
        if result.state == "available" and result.traversal_complete:
            self.last_success_ms = self.clock[0]
        return result

    async def read_status(self):
        self.status_calls += 1
        return CollectorStatus("available")

    def health(self):
        if self.state == "unavailable":
            return AdapterHealth("unavailable", self.last_success_ms, ("history",))
        if self.last_success_ms is None:
            return AdapterHealth("unavailable", None, ("not_read",))
        if self.clock[0] - self.last_success_ms > 60_000:
            return AdapterHealth("stale", self.last_success_ms, ("poll_lag",))
        return AdapterHealth("available", self.last_success_ms, ())


class NoopExporter:
    async def recover(self, **_kwargs):
        return None

    async def drain(self, **_kwargs):
        return 0


class NoopScanner:
    def __init__(self):
        self.exporter = NoopExporter()

    async def scan(self, **_kwargs):
        return 0


class NoopProjection:
    async def record_cpamp_read(self, _result):
        return None

    async def health(self):
        return {"state": "unavailable"}


class RecordingProjection(NoopProjection):
    def __init__(self, *, fail=False):
        self.reads = []
        self.fail = fail

    async def record_cpamp_read(self, result):
        if self.fail:
            raise StorageUnavailable("audit unavailable")
        self.reads.append(result)


class NoopRetention:
    async def run(self, **_kwargs):
        return None


def supervisor(adapter, *, history_enabled=True, projection=None):
    return OperationsSupervisor(
        adapter=adapter,
        projection=projection or NoopProjection(),
        scanner=NoopScanner(),
        exporter=NoopExporter(),
        retention=NoopRetention(),
        interval_seconds=30,
        retention_interval_seconds=3600,
        scan_limit=10,
        drain_limit=10,
        history_enabled=history_enabled,
    )


def test_worker_history_probe_keeps_cpamp_unavailable_without_a_durable_read():
    async def run():
        adapter = FakeAdapter(ReadResult((), "unavailable", False, reasons=("transport",)))
        worker = supervisor(adapter)
        await worker.tick(now=datetime(2026, 10, 27, tzinfo=UTC))
        assert worker.collector is None
        assert worker.status["cpamp_status"]["state"] == "degraded"
        assert adapter.status_calls == 0
        await worker.tick(now=datetime(2026, 10, 27, tzinfo=UTC))
        assert worker.collector is None
        assert worker.status["cpamp_status"]["state"] == "degraded"
        assert adapter.status_calls == 0

    asyncio.run(run())


def test_worker_history_probe_allows_cpamp_after_authenticated_history_read():
    async def run():
        adapter = FakeAdapter(ReadResult((), "available", True))
        worker = supervisor(adapter)
        await worker.tick(now=datetime(2026, 10, 27, tzinfo=UTC))
        assert worker.collector.state == "available"
        assert worker.status["cpamp_status"]["state"] == "available"
        assert adapter.status_calls == 1

    asyncio.run(run())


def test_worker_history_probe_audits_its_durable_read_before_status():
    async def run():
        history = ReadResult((), "available", True)
        adapter = FakeAdapter(history)
        projection = RecordingProjection()
        worker = supervisor(adapter, projection=projection)
        await worker.tick(now=datetime(2026, 10, 27, tzinfo=UTC))
        assert projection.reads == [history]
        assert adapter.status_calls == 1
        assert worker.collector.state == "available"

    asyncio.run(run())


def test_worker_history_probe_fails_closed_when_read_audit_storage_fails():
    async def run():
        adapter = FakeAdapter(ReadResult((), "available", True))
        projection = RecordingProjection(fail=True)
        worker = supervisor(adapter, projection=projection)
        await worker.tick(now=datetime(2026, 10, 27, tzinfo=UTC))
        assert worker.collector is None
        assert worker.status["cpamp_status"]["state"] == "degraded"
        assert adapter.status_calls == 0

    asyncio.run(run())


def test_worker_proof_disabled_uses_collector_without_history_read():
    async def run():
        adapter = FakeAdapter(ReadResult((), "unavailable", False, reasons=("transport",)))
        worker = supervisor(adapter, history_enabled=False)
        await worker.tick(now=datetime(2026, 10, 27, tzinfo=UTC))
        assert worker.collector.state == "available"
        assert worker.status["cpamp_status"]["state"] == "available"
        assert adapter.status_calls == 1
        assert adapter.last_success is None

    asyncio.run(run())


def test_worker_reprobes_history_after_stale_threshold_and_recovers_after_failure():
    async def run():
        clock = [0]
        adapter = ClockedAdapter(
            [
                ReadResult((), "available", True),
                ReadResult((), "unavailable", False, reasons=("transport",)),
                ReadResult((), "available", True),
            ],
            clock,
        )
        worker = supervisor(adapter)
        first = datetime(2026, 10, 27, tzinfo=UTC)
        await worker.tick(now=first)
        assert adapter.history_calls == 1
        assert worker_operations_ready(
            operations_health(
                now=first,
                postgres=True,
                keycloak=True,
                cliproxyapi=True,
                adapter=adapter.health(),
                collector=worker.collector,
                projection=ProjectionHealth(True, first),
                exporter=ExportHealth(False),
            )
        )

        clock[0] = 60_001
        second = first.replace(second=1)
        await worker.tick(now=second)
        assert adapter.history_calls == 2
        assert worker.collector is None
        assert not worker_operations_ready(
            operations_health(
                now=second,
                postgres=True,
                keycloak=True,
                cliproxyapi=True,
                adapter=adapter.health(),
                collector=CollectorStatus("degraded"),
                projection=ProjectionHealth(True, second),
                exporter=ExportHealth(False),
            )
        )

        clock[0] = 60_002
        third = first.replace(second=2)
        await worker.tick(now=third)
        assert adapter.history_calls == 3
        assert worker.collector.state == "available"
        assert worker_operations_ready(
            operations_health(
                now=third,
                postgres=True,
                keycloak=True,
                cliproxyapi=True,
                adapter=adapter.health(),
                collector=worker.collector,
                projection=ProjectionHealth(True, third),
                exporter=ExportHealth(False),
            )
        )

    asyncio.run(run())
