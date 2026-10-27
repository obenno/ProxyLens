"""Atomic, replay-safe projection of CPAMP reads; ownership resolved on every read."""

import asyncio
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from proxylens.correlation import UsageIdentity
from proxylens.cpamp import CPAMPAdapter, HistoryWindow, ReadResult
from proxylens.db import Database, StorageUnavailable
from proxylens.identity import Capability, Principal
from proxylens.lineage import LineageRepository
from proxylens.operations import RetentionPolicy, retention_cutoffs
from proxylens.projection_settings import DISABLED_PROOF_GATE, ProjectionSettings, ProofGate


async def apply_projection_migration(connection) -> None:
    """Apply 010 after 003; resources are required only when queries run."""
    await connection.execute(
        (Path(__file__).with_name("migrations") / "010_projection.sql").read_text()
    )


def _now_ms():
    return time.time_ns() // 1_000_000


class ProjectionRepository:
    def __init__(
        self,
        database: Database,
        settings: ProjectionSettings,
        *,
        clock_ms=_now_ms,
        retention: RetentionPolicy | None = None,
    ):
        self.database, self.settings, self.clock_ms = database, settings, clock_ms
        self.retention = retention or RetentionPolicy(projection_days=settings.retention_days)

    @staticmethod
    async def _integration_audit(conn, action: str, *, outcome: str, details: dict) -> None:
        if action not in {
            "integration.cpamp.read",
            "integration.projection.promote",
            "integration.projection.failure",
        } or outcome not in {"success", "denied"}:
            raise ValueError("invalid integration audit")
        await conn.execute(
            "INSERT INTO resource_audit(id, actor, action, outcome, details) "
            "VALUES (%s, %s, %s, %s, %s)",
            (uuid4(), "system:worker", action, outcome, Jsonb(details)),
        )

    async def record_cpamp_read(self, result: ReadResult) -> None:
        """Record bounded CPAMP traversal facts without copying source rows."""
        async with self.database.transaction() as conn:
            await self._integration_audit(
                conn,
                "integration.cpamp.read",
                outcome="success" if result.state != "unavailable" else "denied",
                details={
                    "state": result.state,
                    "traversal_complete": result.traversal_complete,
                    "pages": result.pages,
                    "records": len(result.records),
                    "rejected": result.rejected_count,
                    "duplicates": result.duplicate_count,
                    "reasons": sorted(result.reasons),
                },
            )

    async def source_state(self):
        async with self.database.transaction() as conn:
            return await (
                await conn.execute(
                    "SELECT * FROM projection_sources WHERE cpamp_instance_id = %s",
                    (self.settings.cpamp_instance_id,),
                )
            ).fetchone()

    async def begin(self, start, end):
        run_id = uuid4()
        config = self.settings
        async with self.database.transaction() as conn:
            await retention_cutoffs(
                conn,
                self.retention,
                now=datetime.fromtimestamp(self.clock_ms() / 1000, UTC),
            )
            await conn.execute(
                "INSERT INTO projection_sources(cpamp_instance_id, cpa_instance_id, binding) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (config.cpamp_instance_id, config.cpa_instance_id, Jsonb(asdict(config.binding))),
            )
            state = await (
                await conn.execute(
                    "SELECT binding FROM projection_sources "
                    "WHERE cpamp_instance_id = %s FOR UPDATE",
                    (config.cpamp_instance_id,),
                )
            ).fetchone()
            if state["binding"] != asdict(config.binding):
                raise ValueError("projection_binding_changed")
            await conn.execute(
                "DELETE FROM projection_runs WHERE cpamp_instance_id = %s",
                (config.cpamp_instance_id,),
            )
            await conn.execute(
                "INSERT INTO projection_runs(run_id, cpamp_instance_id, from_ms, to_ms) "
                "VALUES (%s, %s, %s, %s)",
                (run_id, config.cpamp_instance_id, start, end),
            )
        return run_id

    async def stage(self, run_id, result: ReadResult):
        async with self.database.transaction() as conn:
            cutoffs = await retention_cutoffs(
                conn,
                self.retention,
                now=datetime.fromtimestamp(self.clock_ms() / 1000, UTC),
            )
            cutoff_ms = int(cutoffs.projection.timestamp() * 1000)
            for record in result.records:
                if record.timestamp_ms < cutoff_ms:
                    raise ValueError("retention_expired")
                if (
                    record.instance_id != self.settings.cpamp_instance_id
                    or record.cpamp_version != self.settings.binding.cpamp_version
                ):
                    raise ValueError("projection_binding_changed")
                facts = asdict(record)
                # Only explicit usage facts; account/session/hash metadata is not tenant data.
                facts.pop("metadata")
                facts["native_ids"] = {
                    "provider_trace_id": record.metadata.get("header_trace_id"),
                }
                identity = UsageIdentity.from_cpamp(
                    record.instance_id,
                    record.event_hash,
                    self.settings.cpa_instance_id,
                    record.request_id,
                )
                facts["request_id"] = (
                    str(identity.cpa_request_id) if identity.cpa_request_id else None
                )
                cursor = await conn.execute(
                    "INSERT INTO projection_stage(run_id, event_hash, timestamp_ms, facts) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (run_id, event_hash) DO UPDATE "
                    "SET facts = EXCLUDED.facts WHERE projection_stage.facts = EXCLUDED.facts "
                    "RETURNING event_hash",
                    (run_id, record.event_hash, record.timestamp_ms, Jsonb(facts)),
                )
                if await cursor.fetchone() is None:
                    raise ValueError("conflicting_staged_record")

    async def promote(self, run_id, *, reconcile, coverage, reasons, duplicate_count):
        """All staged windows + lineage + checkpoint publish in ONE transaction.

        Analytics is not a snapshot. Merge retained facts; never infer source deletion
        from absence. Only local retention deletes, at strictly older than the cutoff.
        """
        config = self.settings
        now = self.clock_ms()
        async with self.database.transaction() as conn:
            cutoffs = await retention_cutoffs(
                conn,
                self.retention,
                now=datetime.fromtimestamp(now / 1000, UTC),
            )
            cutoff = max(1, int(cutoffs.projection.timestamp() * 1000))
            run = await (
                await conn.execute(
                    "SELECT * FROM projection_runs WHERE run_id = %s FOR UPDATE",
                    (run_id,),
                )
            ).fetchone()
            if run is None or run["cpamp_instance_id"] != config.cpamp_instance_id:
                raise ValueError("projection_run_missing")
            previous = await (
                await conn.execute(
                    "SELECT coverage, reasons FROM projection_sources "
                    "WHERE cpamp_instance_id=%s FOR UPDATE",
                    (config.cpamp_instance_id,),
                )
            ).fetchone()
            # A later window with no coverage object cannot erase observed historical loss.
            coverage = previous["coverage"] + [c for c in coverage if c not in previous["coverage"]]
            absent = await (
                await conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM projection_records p "
                    "WHERE p.cpamp_instance_id=%s AND p.timestamp_ms >= %s "
                    "AND p.timestamp_ms < %s AND NOT EXISTS (SELECT 1 FROM projection_stage s "
                    "WHERE s.run_id=%s AND s.event_hash=p.event_hash)) AS absent",
                    (config.cpamp_instance_id, max(cutoff, run["from_ms"]), run["to_ms"], run_id),
                )
            ).fetchone()
            if absent["absent"] or (
                not reconcile and "retained_source_absence" in previous["reasons"]
            ):
                reasons.add("retained_source_absence")
            lineage = LineageRepository(conn)
            # Server cursor keeps a retained-history run from becoming one giant Python list.
            async with conn.cursor(name="projection_promotion") as cursor:
                await cursor.execute(
                    "SELECT * FROM projection_stage WHERE run_id = %s AND timestamp_ms >= %s "
                    "ORDER BY event_hash",
                    (run_id, cutoff),
                )
                async for row in cursor:
                    result = await lineage.record_event(
                        UsageIdentity.from_cpamp(
                            config.cpamp_instance_id,
                            row["event_hash"],
                            config.cpa_instance_id,
                            row["facts"]["request_id"],
                        )
                    )
                    duplicate_count += result.status == "duplicate"
                    await conn.execute(
                        "INSERT INTO projection_records "
                        "(cpamp_instance_id, event_hash, timestamp_ms, facts) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT (cpamp_instance_id, event_hash) DO UPDATE SET "
                        "timestamp_ms = EXCLUDED.timestamp_ms, facts = EXCLUDED.facts",
                        (
                            config.cpamp_instance_id,
                            row["event_hash"],
                            row["timestamp_ms"],
                            Jsonb(row["facts"]),
                        ),
                    )
            await conn.execute(
                "DELETE FROM projection_records WHERE cpamp_instance_id = %s AND timestamp_ms < %s",
                (config.cpamp_instance_id, cutoff),
            )
            await conn.execute(
                "UPDATE projection_sources SET last_success_ms=%s, last_attempt_ms=%s, "
                "last_reconcile_ms=CASE WHEN %s THEN %s ELSE last_reconcile_ms END, "
                "window_from_ms=%s, window_to_ms=%s, coverage=%s, reasons=%s, "
                "failed=false, duplicate_count=%s WHERE cpamp_instance_id=%s",
                (
                    now,
                    now,
                    reconcile,
                    now,
                    run["from_ms"],
                    run["to_ms"],
                    Jsonb(coverage),
                    Jsonb(sorted(reasons)),
                    duplicate_count,
                    config.cpamp_instance_id,
                ),
            )
            await conn.execute("DELETE FROM projection_runs WHERE run_id = %s", (run_id,))
            await self._integration_audit(
                conn,
                "integration.projection.promote",
                outcome="success",
                details={
                    "reconcile": reconcile,
                    "duplicate_count": duplicate_count,
                    "reason_count": len(reasons),
                },
            )

    async def failed(self, reasons):
        async with self.database.transaction() as conn:
            await conn.execute(
                "UPDATE projection_sources SET last_attempt_ms=%s, failed=true, "
                "reasons=CASE WHEN reasons ? 'retained_source_absence' "
                "THEN %s::jsonb || '[\"retained_source_absence\"]'::jsonb ELSE %s::jsonb END "
                "WHERE cpamp_instance_id=%s",
                (
                    self.clock_ms(),
                    Jsonb(sorted(set(reasons))),
                    Jsonb(sorted(set(reasons))),
                    self.settings.cpamp_instance_id,
                ),
            )
            await self._integration_audit(
                conn,
                "integration.projection.failure",
                outcome="denied",
                details={"reason_count": len(set(reasons))},
            )

    async def diagnostic_records(self, *, limit=200, offset=0):
        """Trusted internal diagnostics, NOT a tenant or exporter authorization boundary."""
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("invalid projection page")
        async with self.database.transaction() as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM projection_resolved WHERE cpamp_instance_id = %s "
                    "ORDER BY timestamp_ms DESC, event_hash LIMIT %s OFFSET %s",
                    (self.settings.cpamp_instance_id, limit, offset),
                )
            ).fetchall()
        return [self.record(row) for row in rows]

    @staticmethod
    def record(row):
        return {
            **row["facts"],
            "correlation_status": row["correlation_status"],
            "proxylens_request_id": str(row["request_id"]) if row["request_id"] else None,
            "group_id": row["group_id"],
            "application_id": row["application_id"],
        }

    async def health(self):
        state = await self.source_state()
        if state is not None and state["binding"] != asdict(self.settings.binding):
            return {
                "state": "unavailable",
                "last_success_ms": None,
                "coverage": "unknown",
                "source_watermark_ms": None,
                "reasons": ["projection_binding_changed"],
            }
        if state is None or state["last_success_ms"] is None:
            return {
                "state": "unavailable",
                "last_success_ms": None,
                "coverage": "unknown",
                "reasons": state["reasons"] if state else ["not_synced"],
                "source_watermark_ms": None,
            }
        reasons = set(state["reasons"])
        async with self.database.transaction() as conn:
            counts = await (
                await conn.execute(
                    "SELECT correlation_status, count(*) AS n FROM projection_resolved "
                    "WHERE cpamp_instance_id=%s GROUP BY correlation_status",
                    (self.settings.cpamp_instance_id,),
                )
            ).fetchall()
            qualities = await (
                await conn.execute(
                    "SELECT DISTINCT facts#>>'{normalized,quality}' AS quality "
                    "FROM projection_records WHERE cpamp_instance_id=%s",
                    (self.settings.cpamp_instance_id,),
                )
            ).fetchall()
            pending = await (
                await conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM lineage_native_binding b "
                    "JOIN lineage_ingress i USING (request_id) "
                    "WHERE b.cpa_instance_id=%s AND i.keycloak_issuer=%s "
                    "AND i.accepted_at >= to_timestamp(%s / 1000.0) "
                    "AND i.accepted_at <= to_timestamp(%s / 1000.0) "
                    "AND NOT EXISTS (SELECT 1 FROM projection_resolved p "
                    "WHERE p.cpamp_instance_id=%s AND p.request_id=i.request_id "
                    "AND p.cpa_request_id=b.cpa_request_id)) AS pending",
                    (
                        self.settings.cpa_instance_id,
                        self.settings.keycloak_issuer,
                        self.clock_ms() - self.settings.retention_days * 86_400_000,
                        self.clock_ms() - self.settings.stale_after_ms,
                        self.settings.cpamp_instance_id,
                    ),
                )
            ).fetchone()
        for row in qualities:
            if row["quality"] in {"unknown", "inconsistent"}:
                reasons.add("normalization_" + row["quality"])
        if pending["pending"]:
            reasons.add("expected_usage_lag")
        if any(row["correlation_status"] != "correlated" for row in counts):
            reasons.add("uncorrelated_records")
        coverage = (
            "incomplete"
            if any(
                not c["raw_complete"] or c.get("raw_deleted_event_count", 0)
                for c in state["coverage"]
            )
            else "unknown"
        )
        if coverage == "incomplete":
            reasons.add("retention_gap")
        stale = (
            state["failed"]
            or pending["pending"]
            or self.clock_ms() - state["last_success_ms"] >= self.settings.stale_after_ms
            or self.clock_ms() - state["window_to_ms"] >= self.settings.stale_after_ms
        )
        if stale:
            reasons.add("refresh_failed" if state["failed"] else "refresh_lag")
        return {
            "state": "stale" if stale else "degraded" if reasons else "available",
            "last_success_ms": state["last_success_ms"],
            "coverage": coverage,
            "coverage_details": state["coverage"],
            "source_watermark_ms": None,
            "window_from_ms": state["window_from_ms"],
            "window_to_ms": state["window_to_ms"],
            "reasons": sorted(reasons),
            "duplicate_count": state["duplicate_count"],
        }

    async def query(
        self,
        principal: Principal,
        *,
        group_id=None,
        application_id=None,
        event_hash=None,
        from_ms=None,
        to_ms=None,
        limit=100,
        offset=0,
    ):
        """Current authorized view; caller MUST verify proof gate before publication.

        Known totals are always null at this pin: completed HTTP traversal is not
        completeness evidence. Observed aggregates describe only returned-source facts.
        """
        if not principal.has_capability(Capability.READ):
            raise HTTPException(403, "scope_denied")
        if principal.issuer != self.settings.keycloak_issuer:
            raise HTTPException(403, "scope_denied")
        state = await self.source_state()
        if state is None or state["last_success_ms"] is None:
            raise HTTPException(503, "projection_unavailable")
        if state["binding"] != asdict(self.settings.binding):
            raise HTTPException(503, "projection_binding_changed")
        if group_id is not None:
            principal.require(Capability.READ, group_id)
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("invalid projection page")
        if from_ms is not None and to_ms is not None and from_ms >= to_ms:
            raise HTTPException(422, "invalid_usage_window")
        conditions = [
            "p.cpamp_instance_id=%s",
            "p.keycloak_issuer=%s",
            "p.correlation_status='correlated'",
        ]
        args = [self.settings.cpamp_instance_id, principal.issuer]
        if not principal.is_platform_admin:
            conditions.append("p.group_id = ANY(%s)")
            args.append(sorted(principal.group_ids))
        for column, value, operator in (
            ("group_id", group_id, "="),
            ("application_id", application_id, "="),
            ("event_hash", event_hash, "="),
            ("timestamp_ms", from_ms, ">="),
            ("timestamp_ms", to_ms, "<"),
        ):
            if value is not None:
                conditions.append(f"p.{column} {operator} %s")
                args.append(value)
        where = " AND ".join(conditions)
        async with self.database.transaction() as conn:
            # One coherent read snapshot for scoped page AND totals; fresh on each HTTP request.
            await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            if application_id is not None:
                application = await (
                    await conn.execute(
                        "SELECT group_id FROM resource_applications WHERE id::text=%s",
                        (application_id,),
                    )
                ).fetchone()
                if application is None or not principal.can(
                    Capability.READ,
                    application["group_id"],
                ):
                    raise HTTPException(404, "not_found")
                if group_id is not None and application["group_id"] != group_id:
                    raise HTTPException(404, "not_found")
            rows = await (
                await conn.execute(
                    "SELECT p.*, g.state AS group_state, a.state AS application_state, "
                    "a.group_id AS current_group_id FROM projection_resolved p "
                    "LEFT JOIN resource_group_refs g ON g.id=p.group_id "
                    "LEFT JOIN resource_applications a ON a.id::text=p.application_id "
                    f"WHERE {where} ORDER BY p.timestamp_ms DESC, p.event_hash LIMIT %s OFFSET %s",
                    (*args, limit, offset),
                )
            ).fetchall()
            totals = await (
                await conn.execute(
                    "SELECT count(*) AS observed_records, "
                    "CASE WHEN count(*) > 0 AND count(*) FILTER "
                    "(WHERE facts#>>'{normalized,quality}'='derived')=count(*) "
                    "THEN sum((facts#>>'{normalized,total_tokens}')::numeric) "
                    "END AS observed_tokens, "
                    "count(*) FILTER (WHERE facts#>>'{normalized,quality}'<>'derived') "
                    "AS unknown_token_records "
                    f"FROM projection_resolved p WHERE {where}",
                    args,
                )
            ).fetchone()
        records = []
        for row in rows:
            record = self.record(row)
            record["orphaned"] = (
                row["group_state"] != "active"
                or row["application_state"] is None
                or row["application_state"] == "orphaned"
                or row["current_group_id"] != row["group_id"]
            )
            records.append(record)
        return {
            "records": records,
            "totals": {
                **totals,
                "total_records": None,
                "total_tokens": None,
                "cost": None,
            },
            "coverage": (await self.health())["coverage"],
        }


class ProjectionWorker:
    def __init__(
        self,
        repository: ProjectionRepository,
        adapter: CPAMPAdapter,
        *,
        gate: ProofGate = DISABLED_PROOF_GATE,
        clock_ms: Callable[[], int] = _now_ms,
    ):
        self.repository, self.adapter = repository, adapter
        self.gate, self.clock_ms = gate, clock_ms
        if adapter.instance_id != repository.settings.cpamp_instance_id:
            raise ValueError("projection_adapter_instance_mismatch")

    async def rebuild_from_export(self):
        """Diagnostic export attempt. This pinned interface cannot prove a snapshot.

        No destructive replacement path is exposed, including for a claimed
        snapshot_verified flag: an independent snapshot contract needs review first.
        """
        if not self.gate.permits(self.repository.settings):
            return False
        result = await self.adapter.read_export()
        await self.repository.failed(set(result.reasons) | {"export_completeness_unverifiable"})
        return False

    async def poll_once(self, *, rebuild=False):
        try:
            return await self._poll_once(rebuild=rebuild)
        except (StorageUnavailable, ValueError) as error:
            # Commit failure preserves old rows/checkpoint. Persist only a fixed safe code.
            with suppress(StorageUnavailable):
                reason = (
                    "retention_expired"
                    if str(error) == "retention_expired"
                    else "projection_commit_or_binding_failure"
                )
                await self.repository.failed([reason])
            return False

    async def _poll_once(self, *, rebuild=False):
        config = self.repository.settings
        if not self.gate.permits(config):
            return False
        end = self.clock_ms()
        # Transaction-scoped lock on its own connection: one worker per source, released on crash.
        async with self.repository.database.transaction() as lock:
            acquired = await (
                await lock.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 10)) AS acquired",
                    (config.cpamp_instance_id,),
                )
            ).fetchone()
            if not acquired["acquired"]:
                return False
            cutoff = max(
                1,
                int(
                    (
                        await retention_cutoffs(
                            lock,
                            self.repository.retention,
                            now=datetime.fromtimestamp(end / 1000, UTC),
                        )
                    ).projection.timestamp()
                    * 1000
                ),
            )
            state = await self.repository.source_state()
            reconcile = (
                rebuild
                or not state
                or state["last_reconcile_ms"] is None
                or end - state["last_reconcile_ms"] >= config.reconcile_seconds * 1000
            )
            start = cutoff if reconcile else max(cutoff, state["window_to_ms"] - config.overlap_ms)
            if start >= end:
                return False
            run_id = await self.repository.begin(start, end)
            reasons, coverage, duplicates = set(), [], 0
            if (end - start + config.window_ms - 1) // config.window_ms > config.max_windows:
                await self.repository.failed(["reconciliation_window_limit"])
                return False
            for window_start in range(start, end, config.window_ms):
                result = await self.adapter.read_window(
                    HistoryWindow(
                        window_start,
                        min(end, window_start + config.window_ms),
                    )
                )
                await self.repository.record_cpamp_read(result)
                if (
                    not result.traversal_complete
                    or result.rejected_count
                    or result.state == "unavailable"
                    or {"count_mismatch", "concurrent_history_change"}.intersection(result.reasons)
                ):
                    await self.repository.failed(result.reasons or ("incomplete_traversal",))
                    return False
                await self.repository.stage(run_id, result)
                reasons.update(result.reasons)
                coverage.extend(c for c in result.coverage if c not in coverage)
                duplicates += result.duplicate_count
            await self.repository.promote(
                run_id,
                reconcile=reconcile,
                coverage=coverage,
                reasons=reasons,
                duplicate_count=duplicates,
            )
            return True

    async def run(self, stop: asyncio.Event):
        """30s start-to-start target; long traversals report stale instead of overlapping."""
        while not stop.is_set():
            started = time.monotonic()
            await self.poll_once()
            delay = max(0.01, self.repository.settings.poll_seconds - (time.monotonic() - started))
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)


@asynccontextmanager
async def projection_worker_lifespan(
    repository: ProjectionRepository,
    adapter: CPAMPAdapter,
    *,
    gate: ProofGate = DISABLED_PROOF_GATE,
    clock_ms=_now_ms,
):
    """Own adapter + task; integrate into the worker service's existing lifespan."""
    async with adapter:
        worker = ProjectionWorker(repository, adapter, gate=gate, clock_ms=clock_ms)
        stop = asyncio.Event()
        task = asyncio.create_task(worker.run(stop), name="cpamp-projection")
        try:
            yield worker
        finally:
            stop.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
