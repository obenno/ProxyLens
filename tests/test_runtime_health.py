import asyncio
from datetime import UTC, datetime

from proxylens.cpamp import AdapterHealth, CollectorStatus, ReadResult
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
    async def health(self):
        return {"state": "unavailable"}


class NoopRetention:
    async def run(self, **_kwargs):
        return None


def supervisor(adapter, *, history_enabled=True):
    return OperationsSupervisor(
        adapter=adapter,
        projection=NoopProjection(),
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
