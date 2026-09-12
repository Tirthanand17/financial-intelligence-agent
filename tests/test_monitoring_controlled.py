from dataclasses import replace

from app.monitoring.controlled import (
    MonitoringDatabaseSnapshot,
    validate_controlled_discovery_delta,
)
from app.monitoring.models import MonitorExecutionResult, MonitorRunOutcome


def _snapshot() -> MonitoringDatabaseSnapshot:
    return MonitoringDatabaseSnapshot(
        documents=5,
        claims=11,
        claim_entity_attributions=11,
        claim_supersessions=1,
        claim_verification_events=2,
        claim_trust_events=0,
        monitor_discoveries=0,
        monitor_runs=0,
        monitor_states=0,
    )


def _success(*, discovered_count: int = 10) -> MonitorExecutionResult:
    return MonitorExecutionResult(
        monitor_id="rbi-press-releases-rss",
        outcome=MonitorRunOutcome.SUCCESS,
        reason="discovery_completed",
        discovered_count=discovered_count,
    )


def test_controlled_delta_accepts_only_monitor_metadata_changes() -> None:
    before = _snapshot()
    staged = replace(
        before,
        monitor_discoveries=10,
        monitor_runs=1,
        monitor_states=1,
    )

    decision = validate_controlled_discovery_delta(
        before,
        staged,
        _success(),
        max_new_documents_per_run=10,
    )

    assert decision.passed is True
    assert decision.reason == "discovery_only_write_boundary_validated"
    assert decision.blockers == ()


def test_existing_queue_items_can_be_reobserved_without_new_rows() -> None:
    before = replace(_snapshot(), monitor_discoveries=10, monitor_runs=3, monitor_states=1)
    staged = replace(before, monitor_runs=4)

    decision = validate_controlled_discovery_delta(
        before,
        staged,
        _success(),
        max_new_documents_per_run=10,
    )

    assert decision.passed is True


def test_document_or_claim_write_fails_validation() -> None:
    before = _snapshot()
    staged = replace(
        before,
        documents=6,
        claims=12,
        monitor_discoveries=1,
        monitor_runs=1,
        monitor_states=1,
    )

    decision = validate_controlled_discovery_delta(
        before,
        staged,
        _success(discovered_count=1),
        max_new_documents_per_run=10,
    )

    assert decision.passed is False
    assert "database:documents_changed" in decision.blockers
    assert "database:claims_changed" in decision.blockers


def test_trust_or_verification_event_write_fails_validation() -> None:
    before = _snapshot()
    staged = replace(
        before,
        claim_verification_events=3,
        claim_trust_events=1,
        monitor_runs=1,
        monitor_states=1,
    )

    decision = validate_controlled_discovery_delta(
        before,
        staged,
        _success(discovered_count=0),
        max_new_documents_per_run=10,
    )

    assert decision.passed is False
    assert "database:claim_verification_events_changed" in decision.blockers
    assert "database:claim_trust_events_changed" in decision.blockers


def test_discovery_delta_cannot_exceed_monitor_bound() -> None:
    before = _snapshot()
    staged = replace(
        before,
        monitor_discoveries=11,
        monitor_runs=1,
        monitor_states=1,
    )

    decision = validate_controlled_discovery_delta(
        before,
        staged,
        _success(discovered_count=10),
        max_new_documents_per_run=10,
    )

    assert decision.passed is False
    assert "database:discovery_delta_out_of_bounds" in decision.blockers


def test_failed_monitor_outcome_is_not_committable() -> None:
    before = _snapshot()
    staged = replace(before, monitor_runs=1, monitor_states=1)
    result = MonitorExecutionResult(
        monitor_id="rbi-press-releases-rss",
        outcome=MonitorRunOutcome.FAILED,
        reason="source_download_failed",
        error_code="transient_network_error",
    )

    decision = validate_controlled_discovery_delta(
        before,
        staged,
        result,
        max_new_documents_per_run=10,
    )

    assert decision.passed is False
    assert "run:failed" in decision.blockers
