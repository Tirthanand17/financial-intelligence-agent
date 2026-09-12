from app.monitoring.controlled import MonitoringDatabaseSnapshot
from app.monitoring.gate_canary import assess_monitoring_gate_canary
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


def test_canary_accepts_monitor_metadata_only_delta() -> None:
    before = _snapshot()
    after = _snapshot(monitor_runs=5)

    decision = assess_monitoring_gate_canary(
        before,
        after,
        _result(),
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=False,
        trust_promotion_enabled=False,
        max_new_documents_per_run=10,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert decision.passed is True
    assert decision.blockers == ()


def test_canary_rejects_auto_ingest_or_trust_gate() -> None:
    decision = assess_monitoring_gate_canary(
        _snapshot(),
        _snapshot(monitor_runs=5),
        _result(),
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=True,
        max_new_documents_per_run=10,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert decision.passed is False
    assert "gate:source_auto_ingest_must_remain_disabled" in decision.blockers
    assert "gate:trust_promotion_must_remain_disabled" in decision.blockers


def test_canary_rejects_knowledge_or_external_mutation() -> None:
    before = _snapshot()
    after = _snapshot(documents=6, monitor_runs=5)

    decision = assess_monitoring_gate_canary(
        before,
        after,
        _result(),
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=False,
        trust_promotion_enabled=False,
        max_new_documents_per_run=10,
        backblaze_b2_delta=100,
        qdrant_points_delta=1,
    )

    assert decision.passed is False
    assert "database:documents_changed" in decision.blockers
    assert "external:backblaze_changed" in decision.blockers
    assert "external:qdrant_changed" in decision.blockers


def test_canary_rejects_monitoring_gate_off() -> None:
    decision = assess_monitoring_gate_canary(
        _snapshot(),
        _snapshot(monitor_runs=5),
        _result(),
        source_monitoring_enabled=False,
        source_auto_ingest_enabled=False,
        trust_promotion_enabled=False,
        max_new_documents_per_run=10,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert decision.passed is False
    assert "gate:source_monitoring_not_enabled" in decision.blockers
