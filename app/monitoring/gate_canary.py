from dataclasses import dataclass

from app.monitoring.controlled import (
    MonitoringDatabaseSnapshot,
    validate_controlled_discovery_delta,
)
from app.monitoring.models import MonitorExecutionResult


@dataclass(frozen=True, slots=True)
class MonitoringGateCanaryDecision:
    passed: bool
    reason: str
    blockers: tuple[str, ...] = ()


def assess_monitoring_gate_canary(
    before: MonitoringDatabaseSnapshot,
    after: MonitoringDatabaseSnapshot,
    result: MonitorExecutionResult,
    *,
    source_monitoring_enabled: bool,
    source_auto_ingest_enabled: bool,
    trust_promotion_enabled: bool,
    max_new_documents_per_run: int,
    backblaze_b2_delta: int | None,
    qdrant_points_delta: int | None,
) -> MonitoringGateCanaryDecision:
    """Validate one real source-monitoring run without enabling auto-ingestion.

    Phase 10 proves that the production monitoring gate can be turned on for one
    explicit process while the independent auto-ingestion and trust gates remain
    off. The run may only mutate monitor audit/state and bounded discovery queue
    metadata; knowledge rows, B2 objects and Qdrant points must stay unchanged.
    """
    blockers: list[str] = []

    if not source_monitoring_enabled:
        blockers.append("gate:source_monitoring_not_enabled")
    if source_auto_ingest_enabled:
        blockers.append("gate:source_auto_ingest_must_remain_disabled")
    if trust_promotion_enabled:
        blockers.append("gate:trust_promotion_must_remain_disabled")

    persistence = validate_controlled_discovery_delta(
        before,
        after,
        result,
        max_new_documents_per_run=max_new_documents_per_run,
    )
    blockers.extend(persistence.blockers)

    if backblaze_b2_delta is None:
        blockers.append("external:backblaze_usage_unknown")
    elif backblaze_b2_delta != 0:
        blockers.append("external:backblaze_changed")

    if qdrant_points_delta is None:
        blockers.append("external:qdrant_usage_unknown")
    elif qdrant_points_delta != 0:
        blockers.append("external:qdrant_changed")

    unique = tuple(dict.fromkeys(blockers))
    if unique:
        return MonitoringGateCanaryDecision(
            passed=False,
            reason="monitoring_gate_canary_not_reconciled",
            blockers=unique,
        )

    return MonitoringGateCanaryDecision(
        passed=True,
        reason="monitoring_gate_canary_reconciled",
    )
