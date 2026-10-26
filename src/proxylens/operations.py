"""Typed, transaction-scoped operations hooks. Runtime wiring is deliberately explicit."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from proxylens.db import Database

RETENTION_LOCK = 706769006


@dataclass(frozen=True)
class RetentionPolicy:
    request_days: int = 90
    projection_days: int = 90
    outbox_days: int = 90
    audit_days: int = 365
    remote_observation_days: int = 90

    def __post_init__(self):
        for value in vars(self).values():
            if type(value) is not int or not 1 <= value <= 36500:
                raise ValueError("retention days must be integers between 1 and 36500")

    @classmethod
    def from_environment(cls, env: Mapping[str, str]):
        values = {}
        for name in cls.__dataclass_fields__:
            raw = env.get("PROXYLENS_RETENTION_" + name.upper())
            if raw is not None:
                try:
                    values[name] = int(raw)
                except ValueError:
                    raise ValueError("invalid retention configuration") from None
        return cls(**values)

    def cutoffs(self, now: datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("retention requires an aware clock")
        now = now.astimezone(UTC)
        return RetentionCutoffs(
            now,
            now - timedelta(days=self.request_days),
            now - timedelta(days=self.projection_days),
            now - timedelta(days=self.outbox_days),
            now - timedelta(days=self.audit_days),
        )


@dataclass(frozen=True)
class RetentionCutoffs:
    now: datetime
    request: datetime
    projection: datetime
    outbox: datetime
    audit: datetime

    def accepts_source(self, occurred_at: datetime) -> bool:
        """Import uses source event time, never the local arrival timestamp."""
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("source time must be aware")
        return occurred_at >= self.projection


class RetentionParticipant(Protocol):
    name: str

    async def prune(self, conn: psycopg.AsyncConnection, cutoffs: RetentionCutoffs) -> int:
        """Prune owned local rows; maintain holds; do not commit or call remote APIs."""
        ...


async def retention_cutoffs(
    conn: psycopg.AsyncConnection, policy: RetentionPolicy, *, now: datetime
) -> RetentionCutoffs:
    """Writer hook: call before acquiring row locks; held until transaction completion.

    Importers/exporters must reject old source/request timestamps before writing.
    Shared locking makes admission atomic with a sweep's monotonic floor update.
    """
    cutoffs = policy.cutoffs(now)
    await conn.execute("SELECT pg_advisory_xact_lock_shared(%s)", (RETENTION_LOCK,))
    row = await (
        await conn.execute("SELECT * FROM operations_retention_state WHERE singleton")
    ).fetchone()
    if row is None:
        return cutoffs
    return RetentionCutoffs(
        cutoffs.now,
        max(cutoffs.request, row["request_floor"]),
        max(cutoffs.projection, row["projection_floor"]),
        max(cutoffs.outbox, row["outbox_floor"]),
        cutoffs.audit,
    )


@dataclass(frozen=True)
class RetentionResult:
    lineage_deleted: int
    events_deleted: int
    audit_deleted: int
    participant_deleted: dict[str, int]
    cutoffs: RetentionCutoffs


class RetentionRunner:
    def __init__(
        self,
        database: Database,
        policy: RetentionPolicy,
        participants: Sequence[RetentionParticipant],
    ):
        self.database = database
        self.policy = policy
        self.participants = tuple(participants)
        if sorted(p.name for p in participants) != ["gateway", "outbox", "projection"]:
            raise ValueError("gateway, projection and outbox retention hooks are required")

    async def run(self, *, now: datetime) -> RetentionResult:
        cutoffs = self.policy.cutoffs(now)
        async with self.database.transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (RETENTION_LOCK,))
            row = await (
                await conn.execute(
                    """INSERT INTO operations_retention_state
                       VALUES (true, %s, %s, %s, %s)
                       ON CONFLICT (singleton) DO UPDATE SET
                         request_floor = greatest(operations_retention_state.request_floor,
                                                  excluded.request_floor),
                         projection_floor = greatest(operations_retention_state.projection_floor,
                                                     excluded.projection_floor),
                         outbox_floor = greatest(operations_retention_state.outbox_floor,
                                                 excluded.outbox_floor),
                         updated_at = excluded.updated_at RETURNING *""",
                    (cutoffs.request, cutoffs.projection, cutoffs.outbox, cutoffs.now),
                )
            ).fetchone()
            cutoffs = RetentionCutoffs(
                cutoffs.now,
                row["request_floor"],
                row["projection_floor"],
                row["outbox_floor"],
                cutoffs.audit,
            )
            # Prevent an ingress/binding/event arriving between selection and deletion.
            # Future writers take RETENTION_LOCK shared before locking their own rows.
            await conn.execute(
                "LOCK TABLE lineage_ingress, lineage_native_binding, lineage_usage_event, "
                "operations_retention_hold IN SHARE ROW EXCLUSIVE MODE"
            )
            deleted = {}
            # Expire spool first; projection second; gateway terminal rows last.
            for name in ("outbox", "projection", "gateway"):
                participant = next(p for p in self.participants if p.name == name)
                count = await participant.prune(conn, cutoffs)
                if type(count) is not int or count < 0:
                    raise ValueError("invalid retention participant result")
                deleted[name] = count
            # Preserve the entire native-ID connected component whenever any member
            # must survive. Deleting one side of a collision must never grant ownership.
            await conn.execute(
                """CREATE TEMP TABLE operations_expired ON COMMIT DROP AS
                   WITH RECURSIVE protected(request_id) AS (
                     SELECT i.request_id FROM lineage_ingress i
                     WHERE i.accepted_at >= %s OR EXISTS (
                       SELECT 1 FROM operations_retention_hold h
                       WHERE h.request_id = i.request_id
                     ) OR EXISTS (
                       SELECT 1 FROM lineage_native_binding b JOIN lineage_usage_event e
                         USING (cpa_instance_id, cpa_request_id)
                       WHERE b.request_id = i.request_id AND e.first_seen_at >= %s
                     )
                     UNION
                     SELECT peer.request_id FROM protected p
                     JOIN lineage_native_binding b ON b.request_id = p.request_id
                     JOIN lineage_native_binding peer USING (cpa_instance_id, cpa_request_id)
                   )
                   SELECT request_id FROM lineage_ingress
                   WHERE accepted_at < %s AND request_id NOT IN (SELECT request_id FROM protected)
                """,
                (cutoffs.request, cutoffs.projection, cutoffs.request),
            )
            await conn.execute(
                "DELETE FROM lineage_native_binding WHERE request_id IN "
                "(SELECT request_id FROM operations_expired)"
            )
            events = await conn.execute(
                """DELETE FROM lineage_usage_event e WHERE first_seen_at < %s
                   AND NOT EXISTS (SELECT 1 FROM lineage_native_binding b
                     WHERE b.cpa_instance_id = e.cpa_instance_id
                       AND b.cpa_request_id = e.cpa_request_id)""",
                (cutoffs.projection,),
            )
            lineage = await conn.execute(
                "DELETE FROM lineage_ingress WHERE request_id IN "
                "(SELECT request_id FROM operations_expired)"
            )
            audit = await conn.execute(
                "DELETE FROM resource_audit WHERE occurred_at < %s", (cutoffs.audit,)
            )
            result = RetentionResult(
                lineage.rowcount, events.rowcount, audit.rowcount, deleted, cutoffs
            )
            await conn.execute(
                """INSERT INTO resource_audit
                   (id, actor, action, outcome, occurred_at, details)
                   VALUES (%s, 'system:retention', 'retention.delete', 'success', %s, %s)""",
                (
                    uuid4(),
                    cutoffs.now,
                    Jsonb(
                        {
                            "lineage_deleted": result.lineage_deleted,
                            "events_deleted": result.events_deleted,
                            "audit_deleted": result.audit_deleted,
                            "participant_deleted": deleted,
                            "request_cutoff": cutoffs.request.isoformat(),
                            "projection_cutoff": cutoffs.projection.isoformat(),
                            "outbox_cutoff": cutoffs.outbox.isoformat(),
                            "audit_cutoff": cutoffs.audit.isoformat(),
                        }
                    ),
                ),
            )
        return result
