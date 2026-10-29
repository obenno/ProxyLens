"""Typed, metadata-only immutable Langfuse snapshots. No content-capture interface."""

import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from proxylens.correlation import (
    CorrelationResult,
    CorrelationStatus,
    IngressRequest,
    NativeBinding,
    TenantUsageGate,
    observation_metadata,
    tenant_usage_gate,
)
from proxylens.identity import Principal

_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}", re.ASCII)
_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}", re.ASCII)
_REASONS = {"proof_disabled", "usage_complete", "usage_timeout", "gateway_only"}


class ExportError(Exception):
    """Fixed, redacted error code only; never input values or HTTP response text."""


def _safe(value: str) -> str:
    if not isinstance(value, str) or _SAFE.fullmatch(value) is None:
        raise ExportError("invalid_metadata_reference")
    return value


@dataclass(frozen=True)
class ExclusiveUsage:
    """Already-normalized buckets. No normalization or guesses at the export boundary."""

    input: int | None = None
    input_cached_tokens: int | None = None
    output: int | None = None
    output_reasoning_tokens: int | None = None
    total: int | None = None
    input_cache_creation_tokens: int | None = None
    normalization_version: str = "exclusive-v1"

    def __post_init__(self):
        values = self.values()
        if any(type(value) is not int or not 0 <= value <= 2**53 - 1 for value in values.values()):
            raise ExportError("invalid_usage")
        if len(values) == 6 and sum(v for k, v in values.items() if k != "total") != self.total:
            raise ExportError("inconsistent_usage")
        if (
            self.total is not None
            and sum(v for k, v in values.items() if k != "total") > self.total
        ):
            raise ExportError("inconsistent_usage")
        _safe(self.normalization_version)

    def values(self) -> dict[str, int]:
        return {
            key: value
            for key in (
                "input",
                "input_cached_tokens",
                "output",
                "output_reasoning_tokens",
                "total",
                "input_cache_creation_tokens",
            )
            if (value := getattr(self, key)) is not None
        }

    @property
    def complete(self) -> bool:
        # Missing optional cache writes are never made zero. A supplied total must
        # prove that the supplied mutually exclusive buckets cover all tokens.
        return (
            all(
                getattr(self, key) is not None
                for key in (
                    "input",
                    "input_cached_tokens",
                    "output",
                    "output_reasoning_tokens",
                    "total",
                )
            )
            and sum(v for k, v in self.values().items() if k != "total") == self.total
        )


@dataclass(frozen=True)
class ExportCost:
    amount: float | None = None
    currency: str | None = None
    classification: str = "unknown"
    pricing_version: str | None = None
    source: str | None = None

    def __post_init__(self):
        if self.classification not in {"unknown", "estimated", "authoritative"}:
            raise ExportError("invalid_cost")
        if self.amount is not None and (
            type(self.amount) not in (int, float)
            or not math.isfinite(self.amount)
            or self.amount < 0
            or self.currency is None
            or self.classification == "unknown"
        ):
            raise ExportError("invalid_cost")
        if self.currency is not None and re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise ExportError("invalid_cost")
        if self.classification == "authoritative" and not self.source:
            raise ExportError("cost_authority_evidence_missing")
        for value in (self.pricing_version, self.source):
            if value is not None:
                _safe(value)


@dataclass(frozen=True)
class Observation:
    """Trusted server snapshot, never construct with request dictionaries/**raw metadata."""

    ingress: IngressRequest
    ended_at: datetime
    requested_model: str
    resolved_model: str | None
    provider: str | None
    endpoint: str
    outcome: str
    status_code: int | None
    principal: Principal | None = field(default=None, repr=False)
    binding: NativeBinding | None = None
    correlation: CorrelationResult | None = None
    usage_gate: TenantUsageGate = field(default_factory=tenant_usage_gate)
    usage: ExclusiveUsage | None = None
    cost: ExportCost = field(default_factory=ExportCost)


def serialize_observation(observation: Observation, *, reason: str) -> bytes:
    """Exactly one finalized root generation using the original ingress IDs and times."""
    obs = observation
    ingress = obs.ingress
    if reason not in _REASONS:
        raise ExportError("invalid_finalization_reason")
    if obs.ended_at.tzinfo is None or obs.ended_at < ingress.accepted_at:
        raise ExportError("invalid_observation_interval")
    if obs.endpoint not in {"responses", "chat_completions", "completions", "embeddings"}:
        raise ExportError("invalid_endpoint")
    if obs.outcome not in {"succeeded", "failed", "cancelled", "timeout", "unknown"}:
        raise ExportError("invalid_outcome")
    if obs.status_code is not None and (
        type(obs.status_code) is not int or not 100 <= obs.status_code <= 599
    ):
        raise ExportError("invalid_status_code")
    for value, size in ((ingress.trace_id, 32), (ingress.generation_id, 16)):
        if not re.fullmatch(r"[0-9a-f]{" + str(size) + "}", value) or int(value, 16) == 0:
            raise ExportError("invalid_observation_id")
    session = (
        ingress.session_id if _SESSION.fullmatch(ingress.session_id) else str(ingress.request_id)
    )
    metadata = {
        "proxylens_request_id": str(ingress.request_id),
        "application_id": _safe(ingress.owner.application_id),
        "keycloak_group_id": _safe(ingress.owner.keycloak_group_id),
        "client_key_id": _safe(ingress.owner.client_key_id),
        "requested_model": _safe(obs.requested_model),
        "endpoint": obs.endpoint,
        "outcome": obs.outcome,
        "latency_ms": int((obs.ended_at - ingress.accepted_at).total_seconds() * 1000),
        "identity_kind": "machine",
        "correlation_status": "partial",
        "usage_state": "usage_unproven",
        "cost_classification": "unknown",
        "sink_cost_policy": "possible_sink_inferred_estimate_not_billing",
        "finalization_reason": reason,
    }
    for name in ("resolved_model", "provider"):
        if (value := getattr(obs, name)) is not None:
            metadata[name] = _safe(value)
    if obs.status_code is not None:
        metadata["status_code"] = obs.status_code
    # Shared correlation validation prevents exporting another ingress's source IDs.
    try:
        native = observation_metadata(ingress, obs.correlation, binding=obs.binding)
    except ValueError:
        raise ExportError("lineage_mismatch") from None
    for key in ("cpa_instance_id", "cpa_request_id", "cpamp_instance_id", "cpamp_event_hash"):
        if (
            key == "cpa_request_id"
            and obs.correlation is not None
            and obs.correlation.event.cpa_request_id is None
        ):
            continue
        if key in native:
            metadata[key] = _safe(native[key])
    if obs.correlation:
        metadata["correlation_status"] = obs.correlation.status.value
    proven = (
        obs.usage_gate.enabled
        and not obs.usage_gate.blockers
        and obs.correlation is not None
        and obs.correlation.status == CorrelationStatus.CORRELATED
        and obs.correlation.event.cpa_request_id is not None
    )
    usage = obs.usage.values() if proven and obs.usage else {}
    complete = proven and obs.usage is not None and obs.usage.complete
    metadata["usage_state"] = (
        ("complete" if complete else "partial" if usage else "unknown")
        if proven
        else "usage_unproven"
    )
    if proven and obs.usage:
        metadata["normalization_version"] = obs.usage.normalization_version
        if not complete:
            metadata.update({f"partial_usage_{key}": value for key, value in usage.items()})
    if proven:
        metadata["cost_classification"] = obs.cost.classification
        for key in ("currency", "pricing_version", "source"):
            if (value := getattr(obs.cost, key)) is not None:
                metadata[f"cost_{key}"] = value
        if obs.cost.amount is not None and obs.cost.currency != "USD":
            metadata["cost_export_state"] = "non_usd_not_exported"
    principal = obs.principal
    if principal is not None:
        at = ingress.accepted_at.timestamp()
        if (
            principal.verification != "keycloak-rs256"
            or principal.issuer != ingress.owner.keycloak_issuer
            or principal.subject != ingress.owner.subject
            or not principal.verified_at <= at < principal.expires_at
            or not principal.verified_at <= at < principal.signing_key_valid_until
        ):
            raise ExportError("unverified_subject")
        metadata["identity_kind"] = "human"
    attrs = {
        "langfuse.observation.type": "generation",
        "langfuse.trace.name": "proxylens.request",
        "langfuse.session.id": session,
        "langfuse.observation.level": "DEFAULT" if obs.outcome == "succeeded" else "ERROR",
        **{f"langfuse.observation.metadata.{key}": value for key, value in metadata.items()},
    }
    if obs.resolved_model:
        attrs["langfuse.observation.model.name"] = obs.resolved_model
    if principal is not None:
        attrs["langfuse.user.id"] = _safe(principal.subject)
    if complete:
        # Known absent cache creation need not create an extra zero bucket at the sink.
        if usage.get("input_cache_creation_tokens") == 0:
            usage.pop("input_cache_creation_tokens")
        attrs["langfuse.observation.usage_details"] = json.dumps(usage, sort_keys=True)
    if proven and obs.cost.amount is not None and obs.cost.currency == "USD":
        attrs["langfuse.observation.cost_details"] = json.dumps({"total": obs.cost.amount})
    epoch = datetime(1970, 1, 1, tzinfo=UTC)

    def nanos(value):
        delta = value - epoch
        return str((delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000)

    def attribute(key, value):
        encoded = {"intValue": str(value)} if type(value) is int else {"stringValue": value}
        return {"key": key, "value": encoded}

    span = {
        "traceId": ingress.trace_id,
        "spanId": ingress.generation_id,
        "name": "proxylens.model_request",
        "kind": 2,
        "startTimeUnixNano": nanos(ingress.accepted_at),
        "endTimeUnixNano": nanos(obs.ended_at),
        "attributes": [attribute(key, value) for key, value in attrs.items()],
        "status": {"code": 1 if obs.outcome == "succeeded" else 2},
    }
    return json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {"attributes": [attribute("service.name", "proxylens")]},
                    "scopeSpans": [
                        {"scope": {"name": "proxylens.exporter", "version": "1"}, "spans": [span]}
                    ],
                }
            ]
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
