from dataclasses import dataclass

from app.monitoring.controlled import (
    MonitoringDatabaseSnapshot,
    validate_single_queue_processing_delta,
)
from app.monitoring.processor import DiscoveryProcessingResult


@dataclass(frozen=True, slots=True)
class AutoIngestGateCanaryDecision:
    passed: bool
    reason: str
    blockers: tuple[str, ...] = ()


def assess_auto_ingest_gate_canary(
    before: MonitoringDatabaseSnapshot,
    after: MonitoringDatabaseSnapshot,
    result: DiscoveryProcessingResult,
    *,
    source_monitoring_enabled: bool,
    source_auto_ingest_enabled: bool,
    trust_promotion_enabled: bool,
    expected_content_bytes: int,
    expected_chunk_count: int,
    backblaze_b2_delta: int | None,
    qdrant_points_delta: int | None,
) -> AutoIngestGateCanaryDecision:
    """Validate one real auto-ingest-gate canary.

    Phase 12 temporarily enables the normal monitoring and auto-ingestion gates
    for exactly one already-discovered pending queue row while trust promotion
    remains disabled. The selected item must resolve as either one new ingestion
    or one duplicate, and its cross-store deltas must match that terminal result.
    """
    blockers: list[str] = []

    if not source_monitoring_enabled:
        blockers.append("gate:source_monitoring_not_enabled")
    if not source_auto_ingest_enabled:
        blockers.append("gate:source_auto_ingest_not_enabled")
    if trust_promotion_enabled:
        blockers.append("gate:trust_promotion_must_remain_disabled")
    if expected_content_bytes < 1:
        blockers.append("preflight:content_bytes_not_positive")
    if expected_chunk_count < 1:
        blockers.append("preflight:chunk_count_not_positive")

    persistence = validate_single_queue_processing_delta(
        before,
        after,
        selected_count=result.selected_count,
        ingested_count=result.ingested_count,
        duplicate_count=result.duplicate_count,
        failed_count=result.failed_count,
        rejected_count=result.rejected_count,
    )
    blockers.extend(persistence.blockers)

    if backblaze_b2_delta is None:
        blockers.append("external:backblaze_usage_unknown")
    if qdrant_points_delta is None:
        blockers.append("external:qdrant_usage_unknown")

    if result.ingested_count == 1:
        if backblaze_b2_delta != expected_content_bytes:
            blockers.append("external:b2_delta_not_preflight_bytes")
        if qdrant_points_delta != expected_chunk_count:
            blockers.append("external:qdrant_delta_not_preflight_chunks")
    elif result.duplicate_count == 1:
        if backblaze_b2_delta != 0:
            blockers.append("external:duplicate_changed_b2")
        if qdrant_points_delta != 0:
            blockers.append("external:duplicate_changed_qdrant")

    unique = tuple(dict.fromkeys(blockers))
    if unique:
        return AutoIngestGateCanaryDecision(
            passed=False,
            reason="auto_ingest_gate_canary_not_reconciled",
            blockers=unique,
        )

    return AutoIngestGateCanaryDecision(
        passed=True,
        reason="auto_ingest_gate_canary_reconciled",
    )
