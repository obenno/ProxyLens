"""Durable single-generation outbox; leases fence acknowledgements, never justify resends."""

import json
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from proxylens.correlation import CorrelationStatus
from proxylens.db import Database
from proxylens.exporter import ExportError, Observation, serialize_observation
from proxylens.exporter_settings import ExporterSettings
from proxylens.exporter_transport import DeliveryResult
from proxylens.operations import RetentionPolicy, retention_cutoffs

DEFAULT_RETENTION_POLICY = RetentionPolicy()


@dataclass(frozen=True)
class ExportJob:
    request_id: UUID
    state: str
    payload_hash: str
    attempts: int
    next_attempt_at: datetime
    expires_at: datetime
    last_code: str | None
    remote_snapshot_stale: bool
    late_payload_hash: str | None


@dataclass(frozen=True)
class ExportLease:
    request_id: UUID
    token: UUID
    payload: bytes = field(repr=False)
    attempts: int
    expires_at: datetime
    lease_until: datetime


def _source_identity(observation):
    correlation = observation.correlation
    if (
        observation.binding is None
        or correlation is None
        or correlation.status != CorrelationStatus.CORRELATED
    ):
        return None
    event = correlation.event
    if event.cpa_request_id is None:
        return None
    return (
        event.cpamp_instance_id,
        event.event_hash,
        event.cpa_instance_id,
        observation.ingress.owner.keycloak_issuer,
    )


def _job(row) -> ExportJob:
    return ExportJob(**{name: row[name] for name in ExportJob.__dataclass_fields__})


class ExportRepository:
    def __init__(self, database: Database, settings: ExporterSettings, *, retention=None):
        self.database = database
        self.settings = settings
        self.retention = DEFAULT_RETENTION_POLICY if retention is None else retention

    @asynccontextmanager
    async def transaction(self, connection=None):
        if connection is not None:
            yield connection
        else:
            async with self.database.transaction() as conn:
                yield conn

    async def _count(self, conn, code, *, amount=1):
        await conn.execute(
            "INSERT INTO exporter_counters(destination, code, count) VALUES (%s,%s,%s) "
            "ON CONFLICT(destination,code) DO UPDATE SET "
            "count=exporter_counters.count+EXCLUDED.count",
            (self.settings.destination, code, amount),
        )

    async def enqueue(
        self, observation: Observation, *, now: datetime | None = None, connection=None
    ) -> ExportJob:
        """Idempotent restart scan entry. Disabled proofs finalize gateway-only immediately."""
        proven = observation.usage_gate.enabled and not observation.usage_gate.blockers
        complete = (
            proven
            and observation.usage is not None
            and observation.usage.complete
            and observation.correlation is not None
            and observation.correlation.status == CorrelationStatus.CORRELATED
            and observation.correlation.event.cpa_request_id is not None
        )
        reason = "usage_complete" if complete else "usage_timeout" if proven else "proof_disabled"
        return await self._put(
            observation, reason, waiting=proven and not complete, now=now, connection=connection
        )

    async def finalize(
        self, observation: Observation, *, reason: str, now: datetime | None = None
    ) -> ExportJob:
        """Replace an unattempted draft, or flag late changes without changing frozen bytes."""
        return await self._put(observation, reason, waiting=False, now=now)

    async def _put(self, observation, reason, *, waiting, now, connection=None):
        if not self.settings.enabled:
            raise ExportError("exporter_disabled")
        now = now or datetime.now(UTC)
        payload = serialize_observation(observation, reason=reason)
        digest = sha256(payload).hexdigest()
        ingress = observation.ingress
        # Immutable ownership + IDs + interval start. Never migrate a request to another owner.
        identity = sha256(
            json.dumps(
                [
                    "export-identity-v1",
                    str(ingress.request_id),
                    ingress.trace_id,
                    ingress.generation_id,
                    ingress.owner.keycloak_issuer,
                    ingress.owner.keycloak_group_id,
                    ingress.owner.application_id,
                    ingress.owner.client_key_id,
                    ingress.owner.subject,
                    ingress.accepted_at.astimezone(UTC).isoformat(),
                    observation.endpoint,
                ],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        expires = ingress.accepted_at + timedelta(seconds=self.settings.max_age_seconds)
        source = _source_identity(observation)
        error = None
        job = None
        async with self.transaction(connection) as conn:
            cutoffs = await retention_cutoffs(conn, self.retention, now=now)
            if ingress.accepted_at < max(cutoffs.request, cutoffs.outbox):
                raise ExportError("retention_expired")
            # Capacity check and insert/update must serialize across all destinations/workers.
            await conn.execute("SELECT pg_advisory_xact_lock(706769008)")
            row = await (
                await conn.execute(
                    "SELECT * FROM exporter_outbox WHERE destination=%s "
                    "AND request_id=%s FOR UPDATE",
                    (self.settings.destination, ingress.request_id),
                )
            ).fetchone()
            if row and row["identity_hash"] != identity:
                error = "identity_conflict"
            elif row and (row["attempts"] > 0 or row["state"] not in {"WAITING", "READY"}):
                if row["payload_hash"] != digest:
                    row = await (
                        await conn.execute(
                            "UPDATE exporter_outbox SET remote_snapshot_stale=true, "
                            "late_payload_hash=%s, "
                            "updated_at=%s WHERE destination=%s AND request_id=%s RETURNING *",
                            (digest, now, self.settings.destination, ingress.request_id),
                        )
                    ).fetchone()
                return _job(row)
            elif len(payload) > self.settings.max_payload_bytes:
                error = "payload_limit"
            elif now >= expires:
                error = "export_age_limit"
            else:
                totals = await (
                    await conn.execute(
                        "SELECT count(*) AS rows, coalesce(sum(octet_length(payload)),0) AS bytes "
                        "FROM exporter_outbox WHERE destination=%s",
                        (self.settings.destination,),
                    )
                ).fetchone()
                projected_bytes = (
                    totals["bytes"] + len(payload) - (len(row["payload"]) if row else 0)
                )
                if (
                    not row and totals["rows"] >= self.settings.max_spool_rows
                ) or projected_bytes > self.settings.max_spool_bytes:
                    error = "spool_capacity"
                else:
                    state = "WAITING" if waiting else "READY"
                    if row:
                        # A rescan must never reopen a finalized draft for waiting.
                        state = "READY" if row["state"] == "READY" else state
                        row = await (
                            await conn.execute(
                                "UPDATE exporter_outbox SET payload=%s,payload_hash=%s,state=%s, "
                                "source_cpamp_instance_id=%s,source_event_hash=%s,"
                                "source_cpa_instance_id=%s,source_keycloak_issuer=%s,"
                                "updated_at=%s WHERE destination=%s AND request_id=%s RETURNING *",
                                (
                                    payload,
                                    digest,
                                    state,
                                    *(source or (None, None, None, None)),
                                    now,
                                    self.settings.destination,
                                    ingress.request_id,
                                ),
                            )
                        ).fetchone()
                    else:
                        row = await (
                            await conn.execute(
                                "INSERT INTO exporter_outbox(destination,request_id,trace_id,"
                                "generation_id,"
                                "identity_hash,started_at,created_at,updated_at,finalize_after,expires_at,"
                                "state,payload,payload_hash,next_attempt_at,"
                                "source_cpamp_instance_id,source_event_hash,"
                                "source_cpa_instance_id,source_keycloak_issuer) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                                "RETURNING *",
                                (
                                    self.settings.destination,
                                    ingress.request_id,
                                    ingress.trace_id,
                                    ingress.generation_id,
                                    identity,
                                    ingress.accepted_at,
                                    now,
                                    now,
                                    now + timedelta(seconds=self.settings.usage_wait_seconds),
                                    expires,
                                    state,
                                    payload,
                                    digest,
                                    now,
                                    *(source or (None, None, None, None)),
                                ),
                            )
                        ).fetchone()
                    job = _job(row)
                    await conn.execute(
                        "INSERT INTO operations_retention_hold(participant,reference,request_id) "
                        "SELECT 'outbox', %s, request_id FROM lineage_ingress WHERE request_id=%s "
                        "ON CONFLICT DO NOTHING",
                        (self.settings.destination, ingress.request_id),
                    )
            if error:
                await self._count(conn, error)
        if error:
            raise ExportError(error)
        return job

    async def recover(self, *, now: datetime | None = None, connection=None) -> None:
        """Startup/periodic scan. Lost leases are ambiguous, never automatically replayed."""
        now = now or datetime.now(UTC)
        async with self.transaction(connection) as conn:
            await retention_cutoffs(conn, self.retention, now=now)
            await conn.execute(
                "UPDATE exporter_outbox SET state='UNCERTAIN',last_code='lease_expired',"
                "lease_token=NULL,lease_until=NULL,updated_at=%s "
                "WHERE destination=%s AND state='IN_FLIGHT' AND lease_until<=%s",
                (now, self.settings.destination, now),
            )
            await conn.execute(
                "UPDATE exporter_outbox SET state='DEAD_LETTER',last_code='age_limit',"
                "updated_at=%s WHERE destination=%s "
                "AND state IN ('WAITING','READY','RETRY_WAIT') AND expires_at<=%s",
                (now, self.settings.destination, now),
            )
            await conn.execute(
                "UPDATE exporter_outbox SET state='READY',updated_at=%s "
                "WHERE destination=%s AND state='WAITING' AND finalize_after<=%s",
                (now, self.settings.destination, now),
            )
            await conn.execute(
                "UPDATE exporter_outbox SET state='DEAD_LETTER',last_code='attempt_limit',"
                "updated_at=%s WHERE destination=%s AND state IN ('READY','RETRY_WAIT') "
                "AND attempts>=%s",
                (now, self.settings.destination, self.settings.max_attempts),
            )

    async def claim(self, *, now: datetime | None = None) -> ExportLease | None:
        if not self.settings.enabled:
            return None
        now = now or datetime.now(UTC)
        await self.recover(now=now)
        async with self.database.transaction() as conn:
            await retention_cutoffs(conn, self.retention, now=now)
            while True:
                row = await (
                    await conn.execute(
                        "SELECT * FROM exporter_outbox WHERE destination=%s "
                        "AND state IN ('READY','RETRY_WAIT') "
                        "AND next_attempt_at<=%s AND expires_at>%s "
                        "ORDER BY next_attempt_at,request_id FOR UPDATE SKIP LOCKED LIMIT 1",
                        (self.settings.destination, now, now),
                    )
                ).fetchone()
                if not row:
                    return None
                if not await self._current_source_matches(conn, row):
                    await conn.execute(
                        "UPDATE exporter_outbox SET state='UNCERTAIN',last_code=%s,"
                        "updated_at=%s WHERE destination=%s AND request_id=%s",
                        (
                            "lineage_invalidated",
                            now,
                            self.settings.destination,
                            row["request_id"],
                        ),
                    )
                    await self._count(conn, "lineage_invalidated")
                    continue
                break
            token = uuid4()
            until = now + timedelta(seconds=self.settings.lease_seconds)
            await conn.execute(
                "UPDATE exporter_outbox SET state='IN_FLIGHT',attempts=attempts+1,lease_token=%s,"
                "lease_until=%s,first_attempt_at=coalesce(first_attempt_at,%s),updated_at=%s "
                "WHERE destination=%s AND request_id=%s",
                (token, until, now, now, self.settings.destination, row["request_id"]),
            )
            return ExportLease(
                row["request_id"],
                token,
                bytes(row["payload"]),
                row["attempts"] + 1,
                row["expires_at"],
                until,
            )

    async def _current_source_matches(self, conn, row) -> bool:
        if row["source_event_hash"] is None:
            return True
        current = await (
            await conn.execute(
                "SELECT 1 FROM projection_resolved WHERE cpamp_instance_id=%s "
                "AND event_hash=%s AND cpa_instance_id=%s AND keycloak_issuer=%s "
                "AND request_id=%s AND correlation_status='correlated'",
                (
                    row["source_cpamp_instance_id"],
                    row["source_event_hash"],
                    row["source_cpa_instance_id"],
                    row["source_keycloak_issuer"],
                    row["request_id"],
                ),
            )
        ).fetchone()
        return current is not None

    async def get(self, request_id: UUID) -> ExportJob | None:
        async with self.database.transaction() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM exporter_outbox WHERE destination=%s AND request_id=%s",
                    (self.settings.destination, request_id),
                )
            ).fetchone()
            return _job(row) if row else None

    async def finish(
        self,
        lease: ExportLease,
        result: DeliveryResult,
        *,
        now: datetime | None = None,
        random_fraction: float = 0.5,
    ) -> bool:
        """Fenced terminal acknowledgement or bounded known-nonacceptance retry."""
        now = now or datetime.now(UTC)
        if not math.isfinite(random_fraction) or not 0 <= random_fraction <= 1:
            raise ExportError("invalid_jitter")
        state, code = result.state, result.code
        next_at = now
        if state == "RETRY_WAIT":
            delay = max(
                0.1,
                random_fraction
                * min(
                    self.settings.backoff_cap_seconds,
                    self.settings.backoff_base_seconds * 2 ** min(lease.attempts - 1, 30),
                ),
                result.retry_after_seconds,
            )
            if lease.attempts >= self.settings.max_attempts:
                state, code = "DEAD_LETTER", "attempt_limit"
            elif delay >= max(0, (lease.expires_at - now).total_seconds()):
                state, code = "DEAD_LETTER", "age_limit"
            else:
                next_at = now + timedelta(seconds=delay)
        async with self.database.transaction() as conn:
            await retention_cutoffs(conn, self.retention, now=now)
            changed = await conn.execute(
                "UPDATE exporter_outbox SET state=%s,last_code=%s,next_attempt_at=%s,"
                "lease_token=NULL,lease_until=NULL,updated_at=%s "
                "WHERE destination=%s AND request_id=%s AND state='IN_FLIGHT' "
                "AND lease_token=%s AND lease_until>%s",
                (
                    state,
                    code,
                    next_at,
                    now,
                    self.settings.destination,
                    lease.request_id,
                    lease.token,
                    now,
                ),
            )
            if changed.rowcount == 1:
                await conn.execute(
                    "INSERT INTO resource_audit(id, actor, action, outcome, details) "
                    "VALUES (%s, 'system:worker', 'runtime.export.delivery', %s, %s)",
                    (
                        uuid4(),
                        "success" if state == "ACCEPTED" else "denied",
                        Jsonb({"state": state, "code": code}),
                    ),
                )
            return changed.rowcount == 1

    async def lease_active(self, lease: ExportLease, *, now: datetime | None = None) -> bool:
        """Pre-send fence/age check; a suspended worker must not start an expired send."""
        now = now or datetime.now(UTC)
        await self.recover(now=now)
        async with self.database.transaction() as conn:
            row = await (
                await conn.execute(
                    "SELECT * FROM exporter_outbox WHERE destination=%s AND request_id=%s "
                    "AND state='IN_FLIGHT' AND lease_token=%s AND lease_until>%s AND expires_at>%s",
                    (self.settings.destination, lease.request_id, lease.token, now, now),
                )
            ).fetchone()
            if row is None:
                return False
            if await self._current_source_matches(conn, row):
                return True
            await conn.execute(
                "UPDATE exporter_outbox SET state='UNCERTAIN',last_code=%s,"
                "lease_token=NULL,lease_until=NULL,updated_at=%s "
                "WHERE destination=%s AND request_id=%s AND state='IN_FLIGHT' "
                "AND lease_token=%s",
                (
                    "lineage_invalidated",
                    now,
                    self.settings.destination,
                    lease.request_id,
                    lease.token,
                ),
            )
            await self._count(conn, "lineage_invalidated")
            return False

    async def stats(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        async with self.database.transaction() as conn:
            rows = await (
                await conn.execute(
                    "SELECT state,count(*) AS count,"
                    "coalesce(sum(octet_length(payload)),0) AS bytes,min(created_at) AS oldest,"
                    "count(*) FILTER (WHERE remote_snapshot_stale) AS stale "
                    "FROM exporter_outbox WHERE destination=%s GROUP BY state",
                    (self.settings.destination,),
                )
            ).fetchall()
            counters = await (
                await conn.execute(
                    "SELECT code,count FROM exporter_counters WHERE destination=%s",
                    (self.settings.destination,),
                )
            ).fetchall()
        active = [r for r in rows if r["state"] in {"WAITING", "READY", "RETRY_WAIT", "IN_FLIGHT"}]
        return {
            "enabled": self.settings.enabled,
            "rows": sum(r["count"] for r in rows),
            "bytes": sum(r["bytes"] for r in rows),
            "states": {r["state"]: r["count"] for r in rows},
            "remote_snapshot_stale": sum(r["stale"] for r in rows),
            "oldest_pending_seconds": max(
                (max(0, (now - r["oldest"]).total_seconds()) for r in active), default=0
            ),
            "counters": {r["code"]: r["count"] for r in counters},
        }

    async def prune(self, *, now: datetime | None = None, limit: int = 1000) -> int:
        """Bounded local retention, strictly older cutoff. Not remote deletion proof."""
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ExportError("invalid_prune_limit")
        now = now or datetime.now(UTC)
        async with self.database.transaction() as conn:
            cutoffs = await retention_cutoffs(conn, self.retention, now=now)
            await self.recover(now=now, connection=conn)
            cutoff = max(
                now - timedelta(seconds=self.settings.retention_seconds),
                cutoffs.outbox,
            )
            rows = await (
                await conn.execute(
                    "SELECT request_id FROM exporter_outbox WHERE destination=%s "
                    "AND started_at<%s AND state IN ('ACCEPTED','UNCERTAIN','DEAD_LETTER') "
                    "ORDER BY started_at LIMIT %s FOR UPDATE SKIP LOCKED",
                    (self.settings.destination, cutoff, limit),
                )
            ).fetchall()
            request_ids = [row["request_id"] for row in rows]
            if not request_ids:
                return 0
            deleted = await conn.execute(
                "DELETE FROM exporter_outbox WHERE destination=%s AND request_id = ANY(%s)",
                (self.settings.destination, request_ids),
            )
            await conn.execute(
                "DELETE FROM operations_retention_hold WHERE participant='outbox' "
                "AND reference=%s AND request_id = ANY(%s)",
                (self.settings.destination, request_ids),
            )
            await self._count(conn, "pruned", amount=deleted.rowcount)
            return deleted.rowcount
