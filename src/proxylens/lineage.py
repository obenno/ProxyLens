"""PostgreSQL lineage storage. The caller owns commit/rollback and authorization.

Commit ingress before dispatch. Persist returned IDs on headers, even on streaming
responses. Reads are diagnostic contracts, not tenant-authorized publication APIs.
"""

from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from proxylens.correlation import (
    CorrelationResult,
    CorrelationStatus,
    IngressRequest,
    Ownership,
    UsageIdentity,
    returned_cpa_trace,
)


async def apply_lineage_migration(connection: psycopg.AsyncConnection) -> None:
    """Apply 003 inside the caller's migration transaction; bundled with the package."""
    migration = Path(__file__).with_name("migrations") / "003_lineage.sql"
    await connection.execute(migration.read_text())


class LineageRepository:
    def __init__(self, connection: psycopg.AsyncConnection):
        self.connection = connection

    async def record_ingress(self, request: IngressRequest) -> None:
        owner = request.owner
        await self.connection.execute(
            """INSERT INTO lineage_ingress
               (request_id, keycloak_issuer, keycloak_group_id, application_id,
                client_key_id, subject, accepted_at, trace_id, generation_id, session_id) VALUES
               (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                request.request_id,
                owner.keycloak_issuer,
                owner.keycloak_group_id,
                owner.application_id,
                owner.client_key_id,
                owner.subject,
                request.accepted_at,
                request.trace_id,
                request.generation_id,
                request.session_id,
            ),
        )

    async def get_ingress(self, request_id: UUID) -> IngressRequest | None:
        async with self.connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT * FROM lineage_ingress WHERE request_id = %s", (request_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return IngressRequest(
            row["request_id"],
            Ownership(
                row["keycloak_issuer"],
                row["keycloak_group_id"],
                row["application_id"],
                row["client_key_id"],
                row["subject"],
            ),
            row["accepted_at"],
            row["trace_id"],
            row["generation_id"],
            row["session_id"],
        )

    async def bind_response(
        self,
        request_id: UUID,
        cpa_instance_id: str,
        headers: Iterable[tuple[str, str]],
    ) -> CorrelationStatus:
        """Bind only a returned CPA trace; call immediately when response headers arrive.

        Raw headers/auth index are not persisted. A valid header establishes a
        partial lineage until durable CPAMP events arrive, not live-provider proof.
        """
        trace = returned_cpa_trace(headers)
        if trace is None:
            return CorrelationStatus.MISSING
        await self.connection.execute(
            """INSERT INTO lineage_native_binding (cpa_instance_id, cpa_request_id, request_id)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            (cpa_instance_id, trace.request_id, request_id),
        )
        cursor = await self.connection.execute(
            """SELECT count(*) FROM lineage_native_binding
               WHERE cpa_instance_id = %s AND cpa_request_id = %s""",
            (cpa_instance_id, trace.request_id),
        )
        return (
            CorrelationStatus.AMBIGUOUS
            if (await cursor.fetchone())[0] > 1
            else CorrelationStatus.PARTIAL
        )

    async def record_event(self, event: UsageIdentity) -> CorrelationResult:
        """Retain each CPAMP hash, idempotently. Conflicting replays poison that record."""
        async with self.connection.transaction():
            cursor = await self.connection.execute(
                """INSERT INTO lineage_usage_event
                   (cpamp_instance_id, event_hash, cpa_instance_id, cpa_request_id)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING event_hash""",
                (
                    event.cpamp_instance_id,
                    event.event_hash,
                    event.cpa_instance_id,
                    event.cpa_request_id,
                ),
            )
            inserted = await cursor.fetchone() is not None
            if not inserted:
                await self.connection.execute(
                    """UPDATE lineage_usage_event SET conflicted = true
                       WHERE cpamp_instance_id = %s AND event_hash = %s
                       AND (cpa_instance_id IS DISTINCT FROM %s
                            OR cpa_request_id IS DISTINCT FROM %s)""",
                    (
                        event.cpamp_instance_id,
                        event.event_hash,
                        event.cpa_instance_id,
                        event.cpa_request_id,
                    ),
                )
            result = await self.resolve_event(event.cpamp_instance_id, event.event_hash)
            if not inserted and result.status != CorrelationStatus.AMBIGUOUS:
                return CorrelationResult(result.event, CorrelationStatus.DUPLICATE)
            return result

    async def resolve_event(self, cpamp_instance_id: str, event_hash: str) -> CorrelationResult:
        """Re-resolve on every publication; a previously returned snapshot can go stale."""
        async with self.connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """SELECT * FROM lineage_event_resolution
                   WHERE cpamp_instance_id = %s AND event_hash = %s""",
                (cpamp_instance_id, event_hash),
            )
            row = await cursor.fetchone()
        if row is None:
            raise LookupError("lineage event not found")
        ingress = await self.get_ingress(row["request_id"]) if row["request_id"] else None
        return CorrelationResult(
            UsageIdentity(
                row["cpamp_instance_id"],
                row["event_hash"],
                row["cpa_instance_id"],
                row["cpa_request_id"],
            ),
            CorrelationStatus(row["correlation_status"]),
            ingress,
        )
