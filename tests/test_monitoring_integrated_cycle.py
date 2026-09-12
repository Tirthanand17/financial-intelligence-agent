from app.monitoring.controlled import MonitoringDatabaseSnapshot
from app.monitoring.integrated_cycle import assess_integrated_monitor_stage
from app.monitoring.models import MonitorExecutionResult, MonitorRunOutcome


def _snapshot(**overrides) -> MonitoringDatabaseSnapshot:
    values = dict(
        documents=5,
        claims=20,
        claim_entity_attributions=20,
        claim_supersessions=1,
        claim_verification_events=2,
        claim_trust_events=0,
        monitor_discoveries=10,
        monitor_runs=4,
        monitor_states=1,
    )
    values.update(overrides)
    return MonitoringDatabaseSnapshot(**values)


def _result() -> MonitorExecutionResult:
    return MonitorExecutionResult(
        monitor_id="rbi-press-releases-rss",
        outcome=MonitorRunOutcome.SUCCESS,
        reason="discovery_completed",
        discovered_count=10,
        rejected_discovery_count=0,
        ingested_count=0,
        duplicate_count=0,
    )


def test_integrated_monitor_stage_accepts_metadata_only_with_both_gates_on() -> None:
    decision = assess_integrated_monitor_stage(
        _snapshot(),
        _snapshot(monitor_runs=5),
        _result(),
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=False,
        max_new_documents_per_run=10,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert decision.passed is True
    assert decision.blockers == ()


def test_integrated_monitor_stage_rejects_disabled_required_gate_or_trust() -> None:
    decision = assess_integrated_monitor_stage(
        _snapshot(),
        _snapshot(monitor_runs=5),
        _result(),
        source_monitoring_enabled=False,
        source_auto_ingest_enabled=False,
        trust_promotion_enabled=True,
        max_new_documents_per_run=10,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert decision.passed is False
    assert "gate:source_monitoring_not_enabled" in decision.blockers
    assert "gate:source_auto_ingest_not_enabled" in decision.blockers
    assert "gate:trust_promotion_must_remain_disabled" in decision.blockers


def test_integrated_monitor_stage_rejects_knowledge_or_external_mutation() -> None:
    decision = assess_integrated_monitor_stage(
        _snapshot(),
        _snapshot(documents=6, monitor_runs=5),
        _result(),
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=False,
        max_new_documents_per_run=10,
        backblaze_b2_delta=10,
        qdrant_points_delta=1,
    )

    assert decision.passed is False
    assert "database:documents_changed" in decision.blockers
    assert "external:backblaze_changed_during_monitor_stage" in decision.blockers
    assert "external:qdrant_changed_during_monitor_stage" in decision.blockers
