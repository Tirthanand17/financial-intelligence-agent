from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductionReadinessSnapshot:
    source_monitoring_enabled: bool
    source_auto_ingest_enabled: bool
    trust_promotion_enabled: bool
    capacity_allows_ingestion: bool
    capacity_blockers: tuple[str, ...]
    required_monitor_count: int
    ready_monitor_count: int
    monitors_without_success: int
    monitors_with_failures: int
    india_authority_a_gaps: int
    queue_metadata_anomalies: int
    linked_document_anomalies: int
    orphan_claims: int
    document_integrity_failures: int
    expected_qdrant_points: int
    actual_qdrant_points: int | None
    quality_failed_verified_or_trusted: int
    unexpected_trust_events: int


@dataclass(frozen=True, slots=True)
class ProductionReadinessDecision:
    ready: bool
    blockers: tuple[str, ...]


def assess_production_readiness(
    snapshot: ProductionReadinessSnapshot,
) -> ProductionReadinessDecision:
    """Evaluate the final pre-activation production-readiness contract.

    Phase 17 is intentionally fail closed. This check proves the system is
    internally consistent while all automation/trust gates remain disabled;
    it does not enable recurring execution or trust promotion.
    """
    blockers: list[str] = []

    if snapshot.source_monitoring_enabled:
        blockers.append("gate:source_monitoring_enabled")
    if snapshot.source_auto_ingest_enabled:
        blockers.append("gate:source_auto_ingest_enabled")
    if snapshot.trust_promotion_enabled:
        blockers.append("gate:trust_promotion_enabled")
    if not snapshot.capacity_allows_ingestion:
        blockers.append("capacity:not_safe")
        blockers.extend(f"capacity:{name}" for name in snapshot.capacity_blockers)
    if snapshot.required_monitor_count < 1:
        blockers.append("monitor:none_required")
    if snapshot.ready_monitor_count != snapshot.required_monitor_count:
        blockers.append("monitor:not_all_ready")
    if snapshot.monitors_without_success:
        blockers.append("monitor:missing_success_history")
    if snapshot.monitors_with_failures:
        blockers.append("monitor:consecutive_failures")
    if snapshot.india_authority_a_gaps:
        blockers.append("coverage:india_authority_a_gap")
    if snapshot.queue_metadata_anomalies:
        blockers.append("queue:metadata_anomaly")
    if snapshot.linked_document_anomalies:
        blockers.append("queue:linked_document_anomaly")
    if snapshot.orphan_claims:
        blockers.append("claims:orphan_document")
    if snapshot.document_integrity_failures:
        blockers.append("evidence:integrity_failure")
    if snapshot.actual_qdrant_points is None:
        blockers.append("qdrant:unknown_point_count")
    elif snapshot.actual_qdrant_points != snapshot.expected_qdrant_points:
        blockers.append("qdrant:point_count_mismatch")
    if snapshot.quality_failed_verified_or_trusted:
        blockers.append("claims:quality_failed_high_state")
    if snapshot.unexpected_trust_events:
        blockers.append("trust:unexpected_event")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return ProductionReadinessDecision(
        ready=not unique_blockers,
        blockers=unique_blockers,
    )
