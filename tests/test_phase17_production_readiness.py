from dataclasses import replace

from app.monitoring.production_readiness import (
    ProductionReadinessSnapshot,
    assess_production_readiness,
)


def _healthy() -> ProductionReadinessSnapshot:
    return ProductionReadinessSnapshot(
        source_monitoring_enabled=False,
        source_auto_ingest_enabled=False,
        trust_promotion_enabled=False,
        capacity_allows_ingestion=True,
        capacity_blockers=(),
        required_monitor_count=4,
        ready_monitor_count=4,
        monitors_without_success=0,
        monitors_with_failures=0,
        india_authority_a_gaps=0,
        queue_metadata_anomalies=0,
        linked_document_anomalies=0,
        orphan_claims=0,
        document_integrity_failures=0,
        expected_qdrant_points=31,
        actual_qdrant_points=31,
        quality_failed_verified_or_trusted=0,
        unexpected_trust_events=0,
    )


def test_healthy_snapshot_is_ready() -> None:
    decision = assess_production_readiness(_healthy())
    assert decision.ready
    assert decision.blockers == ()


def test_enabled_runtime_gates_block_readiness() -> None:
    snapshot = replace(
        _healthy(),
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=True,
    )
    decision = assess_production_readiness(snapshot)
    assert not decision.ready
    assert decision.blockers == (
        "gate:source_monitoring_enabled",
        "gate:source_auto_ingest_enabled",
        "gate:trust_promotion_enabled",
    )


def test_capacity_and_monitor_failures_block_readiness() -> None:
    snapshot = replace(
        _healthy(),
        capacity_allows_ingestion=False,
        capacity_blockers=("qdrant",),
        ready_monitor_count=3,
        monitors_without_success=1,
        monitors_with_failures=1,
    )
    decision = assess_production_readiness(snapshot)
    assert not decision.ready
    assert "capacity:qdrant" in decision.blockers
    assert "monitor:not_all_ready" in decision.blockers
    assert "monitor:missing_success_history" in decision.blockers
    assert "monitor:consecutive_failures" in decision.blockers


def test_storage_and_queue_integrity_failures_block_readiness() -> None:
    snapshot = replace(
        _healthy(),
        queue_metadata_anomalies=2,
        linked_document_anomalies=1,
        orphan_claims=1,
        document_integrity_failures=1,
    )
    decision = assess_production_readiness(snapshot)
    assert not decision.ready
    assert "queue:metadata_anomaly" in decision.blockers
    assert "queue:linked_document_anomaly" in decision.blockers
    assert "claims:orphan_document" in decision.blockers
    assert "evidence:integrity_failure" in decision.blockers


def test_qdrant_mismatch_and_quality_debt_in_high_state_block() -> None:
    mismatch = assess_production_readiness(
        replace(
            _healthy(),
            actual_qdrant_points=30,
            quality_failed_verified_or_trusted=1,
            unexpected_trust_events=1,
        )
    )
    assert not mismatch.ready
    assert "qdrant:point_count_mismatch" in mismatch.blockers
    assert "claims:quality_failed_high_state" in mismatch.blockers
    assert "trust:unexpected_event" in mismatch.blockers

    unknown = assess_production_readiness(replace(_healthy(), actual_qdrant_points=None))
    assert not unknown.ready
    assert "qdrant:unknown_point_count" in unknown.blockers
