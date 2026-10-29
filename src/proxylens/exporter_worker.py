"""Bounded worker ticks for a dedicated worker, independent from model forwarding."""

import asyncio
import random
from datetime import UTC, datetime

from proxylens.exporter import ExportError
from proxylens.exporter_repository import ExportRepository
from proxylens.exporter_transport import DeliveryResult, OtlpTransport


class ExportWorker:
    def __init__(
        self,
        repository: ExportRepository,
        transport: OtlpTransport,
        *,
        clock=lambda: datetime.now(UTC),
        random_fraction=random.random,
    ):
        self.repository = repository
        self.transport = transport
        self.clock = clock
        self.random_fraction = random_fraction

    async def drain(self, *, limit: int = 100) -> int:
        """At most limit attempts; schedules retries durably, never sleeps for backoff."""
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ExportError("invalid_drain_limit")
        delivered = 0
        for _ in range(limit):
            lease = await self.repository.claim(now=self.clock())
            if lease is None:
                break
            if not await self.repository.lease_active(lease, now=self.clock()):
                break
            try:
                result = await self.transport.send(lease.payload)
            except asyncio.CancelledError:
                await self.repository.finish(
                    lease,
                    DeliveryResult("UNCERTAIN", "cancelled"),
                    now=self.clock(),
                )
                raise
            # If this commit fails, expiry recovery records uncertainty; no send retry.
            await self.repository.finish(
                lease, result, now=self.clock(), random_fraction=self.random_fraction()
            )
            delivered += 1
        return delivered
