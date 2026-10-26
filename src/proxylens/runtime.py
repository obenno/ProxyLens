"""Runtime source scans, retention participants, and bounded worker ticks."""

import asyncio
import time
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from psycopg.types.json import Jsonb

from proxylens.correlation import (
    CorrelationResult,
    CorrelationStatus,
    NativeBinding,
    TenantUsageGate,
    UsageIdentity,
)
from proxylens.db import StorageUnavailable
from proxylens.exporter import ExclusiveUsage, ExportError, Observation
from proxylens.exporter_worker import ExportWorker
from proxylens.lineage import LineageRepository
from proxylens.operations import (
    RetentionCutoffs,
    RetentionPolicy,
    RetentionRunner,
    retention_cutoffs,
)
from proxylens.projection_settings import DISABLED_PROOF_GATE

DEFAULT_RETENTION_POLICY = RetentionPolicy()
RUNTIME_SCAN_LOCK = 706769009


def _runtime_audit(action: str, *, outcome: str, details: dict) -> tuple:
    """Build fixed-shape audit data; callers must execute it in their transaction."""
    allowed = {
        "runtime.projection.poll",
        "runtime.projection.failure",
        "runtime.export.scan",
        "runtime.export.failure",
        "runtime.retention.participant",
    }
    if action not in allowed or outcome not in {"success", "denied"}:
        raise ValueError("invalid runtime audit")
    return "system:worker", action, outcome, Jsonb(details)


async def write_runtime_audit(conn, action: str, *, outcome: str, details: dict) -> None:
    actor, action, outcome, details = _runtime_audit(action, outcome=outcome, details=details)
    await conn.execute(
        "INSERT INTO resource_audit(id, actor, action, outcome, details) "
        "VALUES (%s, %s, %s, %s, %s)",
        (uuid4(), actor, action, outcome, details),
    )


class CompletionScanner:
    """Scan completed gateway rows and enqueue one immutable observation per request."""

    def __init__(
        self,
        database,
        projection_settings,
        exporter,
        *,
        gate=DISABLED_PROOF_GATE,
        retention=None,
        pending_timeout_seconds=300,
    ):
        self.database, self.settings, self.exporter = database, projection_settings, exporter
        self.gate = gate
        self.retention = DEFAULT_RETENTION_POLICY if retention is None else retention
        if type(pending_timeout_seconds) is not int or pending_timeout_seconds <= 0:
            raise ValueError("pending timeout must be a positive integer")
        self.pending_timeout_seconds = pending_timeout_seconds

    async def observation(self, conn, row, *, now):
        ingress = await LineageRepository(conn).get_ingress(row["request_id"])
        if ingress is None:
            raise ExportError("lineage_missing")

        binding = None
        native = await (
            await conn.execute(
                "SELECT b.*, (SELECT count(*) FROM lineage_native_binding peer "
                "WHERE peer.cpa_instance_id=b.cpa_instance_id "
                "AND peer.cpa_request_id=b.cpa_request_id) AS claims "
                "FROM lineage_native_binding b WHERE request_id=%s AND cpa_instance_id=%s",
                (ingress.request_id, self.settings.cpa_instance_id),
            )
        ).fetchall()
        if len(native) == 1 and native[0]["claims"] == 1:
            binding = NativeBinding(
                native[0]["cpa_instance_id"], native[0]["cpa_request_id"], ingress
            )

        proven = self.gate.permits(self.settings)
        state = await (
            await conn.execute(
                "SELECT binding FROM projection_sources WHERE cpamp_instance_id=%s",
                (self.settings.cpamp_instance_id,),
            )
        ).fetchone()
        proven = proven and state is not None and state["binding"] == asdict(self.settings.binding)

        correlation = usage = resolved = provider = None
        if proven and binding is not None:
            records = await (
                await conn.execute(
                    "SELECT * FROM projection_resolved WHERE cpamp_instance_id=%s "
                    "AND cpa_instance_id=%s AND keycloak_issuer=%s AND request_id=%s "
                    "AND correlation_status='correlated'",
                    (
                        self.settings.cpamp_instance_id,
                        self.settings.cpa_instance_id,
                        self.settings.keycloak_issuer,
                        ingress.request_id,
                    ),
                )
            ).fetchall()
            if len(records) == 1:
                record = records[0]
                correlation = CorrelationResult(
                    UsageIdentity(
                        record["cpamp_instance_id"],
                        record["event_hash"],
                        record["cpa_instance_id"],
                        record["cpa_request_id"],
                    ),
                    CorrelationStatus.CORRELATED,
                    ingress,
                )
                facts = record["facts"]
                normalized = facts.get("normalized", {})
                if normalized.get("quality") == "derived" and normalized.get("buckets") is not None:
                    buckets = normalized["buckets"]
                    usage = ExclusiveUsage(
                        input=buckets.get("input_uncached"),
                        input_cached_tokens=buckets.get("cache_read"),
                        input_cache_creation_tokens=buckets.get("cache_write"),
                        output=buckets.get("output_nonreasoning"),
                        output_reasoning_tokens=buckets.get("reasoning"),
                        total=normalized.get("total_tokens"),
                        normalization_version=normalized.get("version", "exclusive-v1"),
                    )
                resolved = facts.get("resolved_model")
                provider = facts.get("provider")

        # The gateway lifecycle outcome is the only persisted transport result. It
        # is not provider billing evidence, but completed transport is a successful
        # operation for the export status contract.
        outcome = {
            "cancelled": "cancelled",
            "timeout": "timeout",
            "upstream_error": "failed",
            "transport_error": "unknown",
            "internal_error": "unknown",
            "storage_error": "unknown",
            "completed": "succeeded",
            "pending": "unknown",
        }.get(row["outcome"], "unknown")
        blockers = () if proven else ("live_proofs_missing",)
        return Observation(
            ingress,
            row["completed_at"] or now,
            row["requested_model"],
            resolved,
            provider,
            "responses",
            outcome,
            row["http_status"],
            binding=binding,
            correlation=correlation,
            usage=usage,
            usage_gate=TenantUsageGate(proven, blockers),
        )

    async def scan(self, *, now=None, limit=100):
        now = now or datetime.now(UTC)
        if not self.exporter.settings.enabled:
            return 0
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid scan limit")
        count = 0
        failures = 0
        pending_unknown = 0
        async with self.database.transaction() as conn:
            cutoffs = await retention_cutoffs(conn, self.retention, now=now)
            # Serialize source scans with retention and other destinations. The
            # retention shared lock is acquired first to keep the global order.
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (RUNTIME_SCAN_LOCK,))
            rows = await (
                await conn.execute(
                    "SELECT g.* FROM gateway_observations g LEFT JOIN operations_scan s "
                    "ON s.request_id=g.request_id AND s.destination=%s "
                    "WHERE (g.completed_at IS NOT NULL OR "
                    "(g.completed_at IS NULL AND g.dispatch_intent_at <= %s)) "
                    "AND g.accepted_at >= %s "
                    "AND (s.code IS NULL OR s.code NOT IN "
                    "('export_age_limit','retention_expired')) "
                    "ORDER BY s.scanned_at NULLS FIRST, g.completed_at, g.request_id LIMIT %s",
                    (
                        self.exporter.settings.destination,
                        now - timedelta(seconds=self.pending_timeout_seconds),
                        max(cutoffs.request, cutoffs.outbox),
                        limit,
                    ),
                )
            ).fetchall()
            for row in rows:
                code = "enqueued"
                try:
                    observation = await self.observation(conn, row, now=now)
                    await self.exporter.enqueue(observation, now=now, connection=conn)
                    count += 1
                    pending_unknown += row["completed_at"] is None
                except ExportError as error:
                    failures += 1
                    code = str(error)
                    if code not in {
                        "spool_capacity",
                        "export_age_limit",
                        "payload_limit",
                        "invalid_metadata_reference",
                        "identity_conflict",
                        "retention_expired",
                        "lineage_missing",
                    }:
                        code = "invalid_observation"
                await conn.execute(
                    "INSERT INTO operations_scan VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT(destination,request_id) DO UPDATE "
                    "SET scanned_at=EXCLUDED.scanned_at,code=EXCLUDED.code",
                    (self.exporter.settings.destination, row["request_id"], now, code),
                )
            await write_runtime_audit(
                conn,
                "runtime.export.scan" if not failures else "runtime.export.failure",
                outcome="success" if not failures else "denied",
                details={
                    "scanned": len(rows),
                    "enqueued": count,
                    "pending_unknown": pending_unknown,
                    "failures": failures,
                },
            )
        return count


class GatewayRetentionParticipant:
    name = "gateway"

    async def prune(self, conn, cutoffs: RetentionCutoffs) -> int:
        await conn.execute(
            "INSERT INTO operations_retention_hold(participant, reference, request_id) "
            "SELECT 'gateway', request_id::text, request_id FROM gateway_lifecycle "
            "WHERE completed_at IS NULL ON CONFLICT DO NOTHING"
        )
        deleted = await conn.execute(
            "DELETE FROM gateway_lifecycle g USING lineage_ingress i "
            "WHERE g.request_id = i.request_id AND g.completed_at IS NOT NULL "
            "AND i.accepted_at < %s AND NOT EXISTS ("
            "SELECT 1 FROM operations_retention_hold h "
            "WHERE h.request_id=g.request_id) RETURNING g.request_id",
            (cutoffs.request,),
        )
        await conn.execute(
            "DELETE FROM operations_retention_hold h WHERE h.participant='gateway' "
            "AND NOT EXISTS (SELECT 1 FROM gateway_lifecycle g WHERE g.request_id=h.request_id)"
        )
        return deleted.rowcount


class ProjectionRetentionParticipant:
    name = "projection"

    async def prune(self, conn, cutoffs: RetentionCutoffs) -> int:
        await conn.execute(
            "INSERT INTO operations_retention_hold(participant, reference, request_id) "
            "SELECT 'projection', p.event_hash, p.request_id FROM projection_resolved p "
            "WHERE p.request_id IS NOT NULL ON CONFLICT DO NOTHING"
        )
        stale_runs = await conn.execute(
            "DELETE FROM projection_runs WHERE created_at < %s", (cutoffs.projection,)
        )
        deleted = await conn.execute(
            "DELETE FROM projection_records WHERE timestamp_ms < %s",
            (int(cutoffs.projection.timestamp() * 1000),),
        )
        await conn.execute(
            "DELETE FROM operations_retention_hold h WHERE h.participant='projection' "
            "AND NOT EXISTS (SELECT 1 FROM projection_resolved p "
            "WHERE p.request_id=h.request_id)"
        )
        return stale_runs.rowcount + deleted.rowcount


class OutboxRetentionParticipant:
    name = "outbox"

    def __init__(self, repository):
        self.repository = repository

    async def prune(self, conn, cutoffs: RetentionCutoffs) -> int:
        uncertain = await conn.execute(
            "UPDATE exporter_outbox SET state='UNCERTAIN', "
            "last_code='retention_expired_ambiguous', "
            "updated_at=%s, lease_token=NULL, lease_until=NULL "
            "WHERE destination=%s AND started_at < %s "
            "AND state='IN_FLIGHT'",
            (cutoffs.now, self.repository.settings.destination, cutoffs.outbox),
        )
        dead_lettered = await conn.execute(
            "UPDATE exporter_outbox SET state='DEAD_LETTER', last_code='retention_expired', "
            "updated_at=%s WHERE destination=%s AND started_at < %s "
            "AND state IN ('WAITING','READY','RETRY_WAIT')",
            (cutoffs.now, self.repository.settings.destination, cutoffs.outbox),
        )
        deleted = await conn.execute(
            "DELETE FROM exporter_outbox WHERE destination=%s AND started_at < %s "
            "AND state IN ('ACCEPTED','UNCERTAIN','DEAD_LETTER') RETURNING request_id",
            (self.repository.settings.destination, cutoffs.outbox),
        )
        await conn.execute(
            "DELETE FROM operations_retention_hold h WHERE h.participant='outbox' "
            "AND h.reference=%s AND NOT EXISTS (SELECT 1 FROM exporter_outbox o "
            "WHERE o.destination=%s AND o.request_id=h.request_id)",
            (
                self.repository.settings.destination,
                self.repository.settings.destination,
            ),
        )
        changed = uncertain.rowcount + dead_lettered.rowcount + deleted.rowcount
        if changed:
            await conn.execute(
                "INSERT INTO exporter_counters(destination, code, count) "
                "VALUES (%s, 'retention', %s) "
                "ON CONFLICT(destination, code) DO UPDATE SET "
                "count=exporter_counters.count+EXCLUDED.count",
                (self.repository.settings.destination, changed),
            )
        return changed


class OperationsSupervisor:
    """One worker owner for recovery, source scan, delivery, retention, and status."""

    def __init__(
        self,
        *,
        adapter,
        projection,
        scanner: CompletionScanner,
        exporter: ExportWorker,
        retention: RetentionRunner,
        interval_seconds: float,
        retention_interval_seconds: float,
        scan_limit: int,
        drain_limit: int,
    ):
        self.adapter = adapter
        self.projection = projection
        self.scanner = scanner
        self.exporter = exporter
        self.retention = retention
        self.interval_seconds = interval_seconds
        self.retention_interval_seconds = retention_interval_seconds
        self.scan_limit = scan_limit
        self.drain_limit = drain_limit
        self.status = {}
        self.collector = None
        self._last_retention: datetime | None = None

    @staticmethod
    def _mark(status, name, state):
        status[name] = {"state": state, "observed_at": datetime.now(UTC).isoformat()}

    async def _step(self, name, callback):
        try:
            result = await callback()
        except (StorageUnavailable, ExportError, OSError, TimeoutError):
            self._mark(self.status, name, "degraded")
            return None
        except Exception:
            self._mark(self.status, name, "degraded")
            return None
        self._mark(self.status, name, "available")
        return result

    async def tick(self, *, now: datetime | None = None):
        now = now or datetime.now(UTC)
        await self._step("export_recovery", lambda: self.scanner.exporter.recover(now=now))
        await self._step(
            "completion_scan", lambda: self.scanner.scan(now=now, limit=self.scan_limit)
        )
        await self._step("export_drain", lambda: self.exporter.drain(limit=self.drain_limit))
        if (
            self._last_retention is None
            or (now - self._last_retention).total_seconds() >= self.retention_interval_seconds
        ) and await self._step("retention", lambda: self.retention.run(now=now)) is not None:
            self._last_retention = now
        self.collector = await self._step("cpamp_status", self.adapter.read_status)
        await self._step("projection_health", self.projection.health)

    async def run(self, stop: asyncio.Event):
        while not stop.is_set():
            started = time.monotonic()
            await self.tick()
            delay = max(0.01, self.interval_seconds - (time.monotonic() - started))
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)


async def periodic_tick(stop: asyncio.Event, interval: float, callback, *, name: str, status: dict):
    """Run a bounded callback repeatedly; retain only fixed diagnostic state."""
    while not stop.is_set():
        started = time.monotonic()
        try:
            await callback()
            status[name] = {"state": "available", "observed_at": datetime.now(UTC)}
        except asyncio.CancelledError:
            raise
        except Exception:
            status[name] = {"state": "degraded", "observed_at": datetime.now(UTC)}
        delay = max(0.01, interval - (time.monotonic() - started))
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)
