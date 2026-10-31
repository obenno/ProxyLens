"""Redacted health projection from existing dependency probes and adapter status.

No network I/O here: in particular CPAMP alone owns the consumptive CPA queue.
This snapshot is diagnostic, never an authorization or provider-replay decision.
"""

from dataclasses import dataclass
from datetime import datetime

from proxylens.cpamp import AdapterHealth, CollectorStatus


@dataclass(frozen=True)
class ProjectionHealth:
    enabled: bool
    last_success: datetime | None = None
    source_gap: bool = False
    degraded: bool = False
    stale: bool = False


@dataclass(frozen=True)
class ExportHealth:
    enabled: bool
    pending: int | None = None
    uncertain: int | None = None
    dead_letters: int | None = None
    oldest_pending: datetime | None = None
    last_success: datetime | None = None
    available: bool | None = None


def operations_health(
    *,
    now: datetime,
    postgres: bool,
    keycloak: bool,
    cliproxyapi: bool,
    adapter: AdapterHealth,
    collector: CollectorStatus,
    projection: ProjectionHealth,
    exporter: ExportHealth,
    freshness_seconds: int = 60,
) -> dict:
    def age(value):
        return max(0, (now - value).total_seconds()) if value else None

    def count(value):
        return value if type(value) is int and value >= 0 else None

    states = {"available", "unavailable", "degraded", "stale", "disabled", "unknown"}
    adapter_state = adapter.state if adapter.state in states else "unavailable"
    collector_state = collector.state if collector.state in states else "unavailable"
    projection_age = age(projection.last_success)
    if not projection.enabled:
        projection_state = "disabled"
    elif not postgres or projection_age is None:
        projection_state = "unavailable"
    elif projection.source_gap or projection.degraded:
        projection_state = "degraded"
    elif projection.stale or projection_age >= freshness_seconds or adapter_state != "available":
        projection_state = "stale"
    else:
        projection_state = "available"
    if not exporter.enabled:
        export_state = "disabled"
    elif not postgres or exporter.available is False:
        export_state = "unavailable"
    elif exporter.uncertain or exporter.dead_letters:
        export_state = "degraded"
    elif exporter.available is None:
        export_state = "unknown"
    else:
        export_state = "available"
    return {
        "forwarding_ready": postgres and keycloak and cliproxyapi,
        "dependencies": {
            "postgres": {"state": "available" if postgres else "unavailable"},
            "keycloak": {"state": "available" if keycloak else "unavailable"},
            "cliproxyapi": {"state": "available" if cliproxyapi else "unavailable"},
            "cpamp": {
                # The authenticated collector status remains a readiness probe
                # when live proof gates intentionally disable history polling.
                "state": adapter_state if projection.enabled else collector_state,
                "collector_state": collector_state,
                "history_state": adapter_state if projection.enabled else "disabled",
                "history_last_success_ms": count(adapter.last_success_ms),
                "last_consumed_at_ms": count(collector.last_consumed_at_ms),
                "last_inserted_at_ms": count(collector.last_inserted_at_ms),
                "dead_letters": count(collector.dead_letters),
                # The supported status contract has no dropped-event/coverage proof.
                "queue_coverage": "unknown",
            },
            "projection": {
                "state": projection_state,
                "age_seconds": projection_age,
                "source_gap": projection.source_gap,
            },
            "langfuse": {
                "state": export_state,
                "pending": count(exporter.pending),
                "uncertain": count(exporter.uncertain),
                "dead_letters": count(exporter.dead_letters),
                "oldest_pending_seconds": age(exporter.oldest_pending),
                "last_success_age_seconds": age(exporter.last_success),
            },
        },
    }
