"""Projection-only settings and fail-closed, reviewed deployment evidence loading."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from proxylens.cpamp import CPAMP_VERSION


@dataclass(frozen=True)
class DeploymentBinding:
    cpamp_instance_id: str
    cpa_instance_id: str
    keycloak_issuer: str
    cpamp_version: str = CPAMP_VERSION
    cpa_version: str = "v8.0.40"
    cpamp_source: str = "6d962db680085827cd19a778d2ff05a3d1315672"
    cpa_source: str = "d946c4fba6fc9a5cfbca1f3d85184d62ad2fb683"
    correlation_method: str = "cpa-8.0.40-returned-trace-uuid-v1"


@dataclass(frozen=True)
class ProjectionSettings:
    cpamp_instance_id: str
    cpa_instance_id: str
    keycloak_issuer: str
    poll_seconds: int = 30
    stale_after_ms: int = 60_000
    overlap_ms: int = 300_000
    window_ms: int = 86_400_000
    reconcile_seconds: int = 3600
    retention_days: int = 90
    max_windows: int = 1000

    def __post_init__(self):
        for value in (self.cpamp_instance_id, self.cpa_instance_id, self.keycloak_issuer):
            if not isinstance(value, str) or not 1 <= len(value) <= 512 or not value.isprintable():
                raise ValueError("invalid projection deployment reference")
        for value in (
            self.poll_seconds,
            self.stale_after_ms,
            self.overlap_ms,
            self.window_ms,
            self.reconcile_seconds,
            self.retention_days,
            self.max_windows,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("projection timing and bounds must be positive integers")

    @property
    def binding(self) -> DeploymentBinding:
        return DeploymentBinding(self.cpamp_instance_id, self.cpa_instance_id, self.keycloak_issuer)

    @staticmethod
    def required_scenarios(kind: str) -> tuple[str, ...]:
        return {
            "correlation": (
                "two_groups_shared_credential",
                "stream_and_nonstream",
                "tools_multimodal",
                "retry_failover",
                "failure_cancellation",
                "missing_colliding_ids",
                "source_to_visible_under_60s",
            ),
            "durable_history": (
                "full_mode_sole_consumer",
                "authenticated_durable_reads",
                "restart_replay",
                "pagination_late_records",
                "retention_loss_outage",
                "deployed_binary_verified",
            ),
        }[kind]


@dataclass(frozen=True)
class ProofGate:
    binding: DeploymentBinding | None = None
    artifact_sha256: tuple[str, ...] = ()
    enabled: bool = False
    reasons: tuple[str, ...] = ("live_proofs_missing",)

    def permits(self, settings: ProjectionSettings) -> bool:
        return self.enabled and self.binding == settings.binding and len(self.artifact_sha256) == 2


DISABLED_PROOF_GATE = ProofGate()


def load_proof_gate(
    settings: ProjectionSettings,
    artifacts: tuple[Path, ...] | list[Path] = (),
    *,
    approved_sha256: frozenset[str] | set[str] = frozenset(),
    allow_synthetic: bool = False,
) -> ProofGate:
    """Verify externally reviewed digests, both scenarios and exact deployment pins.

    No shipped artifact/digest enables this gate. Digest approvals must come from
    a separate trusted deployment review, never from the artifact being loaded.
    Synthetic opt-in is a Python test seam only; do not expose it via configuration.
    Hash verification attests artifact integrity, not the truth of a human review.
    """
    found: dict[str, str] = {}
    try:
        if len(artifacts) != 2:
            raise ValueError
        for path in artifacts:
            with Path(path).open("rb") as file:
                raw = file.read(65_537)
            digest = hashlib.sha256(raw).hexdigest()
            if len(raw) > 65_536 or digest not in approved_sha256:
                raise ValueError
            body = json.loads(raw)
            kind = body["kind"]
            verified_at = datetime.fromisoformat(body["verified_at"])
            if (
                body["schema_version"] != 1
                or body["status"] != "passed"
                or body["binding"] != asdict(settings.binding)
                or body["provenance"]
                not in (
                    {"live_deployment", "synthetic"} if allow_synthetic else {"live_deployment"}
                )
                or kind in found
                or verified_at.tzinfo is None
                or not set(settings.required_scenarios(kind)).issubset(body["scenarios"])
            ):
                raise ValueError
            found[kind] = digest
        if set(found) != {"correlation", "durable_history"}:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return ProofGate(reasons=("live_proofs_missing_or_invalid",))
    return ProofGate(settings.binding, tuple(found[k] for k in sorted(found)), True, ())
