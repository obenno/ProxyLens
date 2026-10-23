"""Version-pinned CPA returned-ID parsing; never infer identity from request content."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

CPA_TRACE_MAX_LENGTH = 116
_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_TRACE = re.compile(r"[0-9]{14}-([A-Za-z0-9_.]{1,64})-(" + _UUID7 + r")", re.ASCII)


def _reference(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or not value.isprintable():
        raise ValueError("invalid lineage reference")


@dataclass(frozen=True)
class Ownership:
    """Server-resolved references, never caller headers or a local identity authority."""

    keycloak_issuer: str
    keycloak_group_id: str
    application_id: str
    client_key_id: str
    subject: str | None = None

    def __post_init__(self):
        for value in (
            self.keycloak_issuer,
            self.keycloak_group_id,
            self.application_id,
            self.client_key_id,
        ):
            _reference(value)
        if self.subject is not None:
            _reference(self.subject)


@dataclass(frozen=True)
class IngressRequest:
    request_id: UUID
    owner: Ownership
    accepted_at: datetime
    trace_id: str
    generation_id: str
    session_id: str

    def __post_init__(self):
        if not isinstance(self.request_id, UUID) or self.request_id.version != 4:
            raise ValueError("invalid ingress request ID")
        if self.accepted_at.tzinfo is None:
            raise ValueError("ingress timestamp must have timezone")
        for value, length in ((self.trace_id, 32), (self.generation_id, 16)):
            if re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value) is None:
                raise ValueError("invalid observation ID")
        _reference(self.session_id)

    @classmethod
    def new(cls, owner: Ownership) -> "IngressRequest":
        """Generate authoritative IDs; client request/session IDs are deliberately not inputs."""
        request_id = uuid4()
        return cls(
            request_id,
            owner,
            datetime.now(UTC),
            uuid4().hex,
            uuid4().hex[:16],
            str(request_id),
        )


def propagation_headers(request: IngressRequest) -> dict[str, str]:
    """Fresh allowlist for gateway diagnostics, not a promised CPA queue join.

    Gateway must build its outgoing headers separately, adding only its own CPA
    client credential. Do not merge arbitrary inbound headers into this dictionary.
    """
    return {"X-Request-ID": str(request.request_id)}


@dataclass(frozen=True)
class CPATrace:
    request_id: UUID
    auth_index: str = field(repr=False)
    raw: str = field(repr=False)


def parse_cpa_trace_id(value: str | None) -> CPATrace | None:
    """Parse the CPA v8.0.40 returned header, retaining the full UUID."""
    if not isinstance(value, str) or len(value) > CPA_TRACE_MAX_LENGTH:
        return None
    match = _TRACE.fullmatch(value)
    if match is None:
        return None
    return CPATrace(UUID(match[2]), match[1], value)


def returned_cpa_trace(headers: Iterable[tuple[str, str]]) -> CPATrace | None:
    """Use response headers from the configured CPA transport, preserving multiplicity."""
    values = [value for name, value in headers if name.lower() == "x-cpa-trace-id"]
    return parse_cpa_trace_id(values[0]) if len(values) == 1 else None


class CorrelationStatus(StrEnum):
    CORRELATED = "correlated"
    PARTIAL = "partial"
    MISSING = "missing"
    DUPLICATE = "duplicate"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class NativeBinding:
    cpa_instance_id: str
    cpa_request_id: UUID
    ingress: IngressRequest

    def __post_init__(self):
        _reference(self.cpa_instance_id)
        if not isinstance(self.cpa_request_id, UUID) or self.cpa_request_id.version != 7:
            raise ValueError("invalid CPA native request ID")


@dataclass(frozen=True)
class UsageIdentity:
    cpamp_instance_id: str
    event_hash: str
    cpa_instance_id: str
    cpa_request_id: UUID | None

    def __post_init__(self):
        _reference(self.cpamp_instance_id)
        _reference(self.cpa_instance_id)
        if re.fullmatch(r"[0-9a-f]{64}", self.event_hash, re.ASCII) is None:
            raise ValueError("invalid CPAMP event hash")
        if self.cpa_request_id is not None and (
            not isinstance(self.cpa_request_id, UUID) or self.cpa_request_id.version != 7
        ):
            raise ValueError("invalid CPA native request ID")

    @classmethod
    def from_cpamp(
        cls,
        cpamp_instance_id: str,
        event_hash: str,
        cpa_instance_id: str,
        request_id: str | None,
    ) -> "UsageIdentity":
        """Consume only adapter identity fields, never arbitrary raw usage metadata.

        Unknown/malformed native IDs remain missing; no original unsafe value is retained.
        """
        native = (
            UUID(request_id)
            if isinstance(request_id, str)
            and len(request_id) == 36
            and re.fullmatch(_UUID7, request_id, re.ASCII)
            else None
        )
        return cls(cpamp_instance_id, event_hash, cpa_instance_id, native)


@dataclass(frozen=True)
class CorrelationResult:
    event: UsageIdentity
    status: CorrelationStatus
    ingress: IngressRequest | None = None


def correlate(event: UsageIdentity, bindings: Iterable[NativeBinding]) -> CorrelationResult:
    """Exact instance + full native ID matching only; no timestamp/credential heuristics."""
    if event.cpa_request_id is None:
        return CorrelationResult(event, CorrelationStatus.MISSING)
    candidates = {
        binding.ingress
        for binding in bindings
        if (binding.cpa_instance_id, binding.cpa_request_id)
        == (event.cpa_instance_id, event.cpa_request_id)
    }
    if len(candidates) > 1:
        return CorrelationResult(event, CorrelationStatus.AMBIGUOUS)
    if candidates:
        return CorrelationResult(event, CorrelationStatus.CORRELATED, candidates.pop())
    return CorrelationResult(event, CorrelationStatus.PARTIAL)


def observation_metadata(
    request: IngressRequest,
    result: CorrelationResult | None = None,
    *,
    binding: NativeBinding | None = None,
) -> dict[str, str]:
    """Safe metadata for the exporter, not a Langfuse wire payload or usage permit.

    Missing, ambiguous and duplicate events carry no owner and cannot be exported
    under an ingress observation. Export those separately as operator diagnostics.
    """
    if result is not None and result.ingress != request:
        raise ValueError("lineage ownership mismatch")
    if binding is not None and binding.ingress != request:
        raise ValueError("lineage ownership mismatch")
    if (
        binding is not None
        and result is not None
        and (binding.cpa_instance_id, binding.cpa_request_id)
        != (result.event.cpa_instance_id, result.event.cpa_request_id)
    ):
        raise ValueError("lineage native ID mismatch")
    metadata = {
        "proxylens_request_id": str(request.request_id),
        "application_id": request.owner.application_id,
        "keycloak_group_id": request.owner.keycloak_group_id,
        "trace_id": request.trace_id,
        "generation_id": request.generation_id,
        "session_id": request.session_id,
        "correlation_status": str(result.status) if result else "partial",
    }
    if request.owner.subject is not None:
        metadata["user_id"] = request.owner.subject
    if binding is not None:
        metadata["cpa_instance_id"] = binding.cpa_instance_id
        metadata["cpa_request_id"] = str(binding.cpa_request_id)
    if result is not None:
        metadata.update(
            {
                "cpa_instance_id": result.event.cpa_instance_id,
                "cpa_request_id": str(result.event.cpa_request_id),
                "cpamp_instance_id": result.event.cpamp_instance_id,
                "cpamp_event_hash": result.event.event_hash,
            }
        )
    return metadata


@dataclass(frozen=True)
class TenantUsageGate:
    enabled: bool
    blockers: tuple[str, ...]


def tenant_usage_gate(*, durable_history_proven: bool = False) -> TenantUsageGate:
    """Release gate: no live correlation evidence exists in this implementation.

    No environment flag or caller-provided boolean can certify correlation. Replace
    this blocker only in an evidence-reviewed change tied to deployed version pins.
    """
    blockers = ("correlation_live_proof_missing",)
    if not durable_history_proven:
        blockers += ("cpamp_live_proof_missing",)
    return TenantUsageGate(False, blockers)
