from dataclasses import dataclass

from app.monitoring.controlled import (
    MonitoringDatabaseSnapshot,
    validate_controlled_discovery_delta,
)
from app.monitoring.models import MonitorExecutionResult


@dataclass(frozen=True, slots=True)
class IntegratedMonitorStageDecision:
    passed: bool
    reason: str
    blockers: tuple[str, ...] = ()


def assess_integrated_monitor_stage(
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
) -> IntegratedMonitorStageDecision:
    """Validate the discovery stage of one integrated monitor+ingest cycle.

    Unlike the Phase 10/11 discovery-only canaries, the integrated cycle may have
    auto-ingestion enabled for the process. The monitor stage itself must still be
    discovery-only: it may update bounded monitor/discovery metadata but may not
    create knowledge rows, objects, vectors, or trust events. Queue processing is
    validated separately after this stage is committed.
    """
    blockers: list[str] = []

    if not source_monitoring_enabled:
        blockers.append("gate:source_monitoring_not_enabled")
    if not source_auto_ingest_enabled:
        blockers.append("gate:source_auto_ingest_not_enabled")
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
        blockers.append("external:backblaze_changed_during_monitor_stage")

    if qdrant_points_delta is None:
        blockers.append("external:qdrant_usage_unknown")
    elif qdrant_points_delta != 0:
        blockers.append("external:qdrant_changed_during_monitor_stage")

    unique = tuple(dict.fromkeys(blockers))
    if unique:
        return IntegratedMonitorStageDecision(
            passed=False,
            reason="integrated_monitor_stage_not_reconciled",
            blockers=unique,
        )

    return IntegratedMonitorStageDecision(
        passed=True,
        reason="integrated_monitor_stage_reconciled",
    )
