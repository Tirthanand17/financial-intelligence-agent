from dataclasses import replace

from app.monitoring.auto_ingest_canary import assess_auto_ingest_gate_canary
from app.monitoring.controlled import MonitoringDatabaseSnapshot
from app.monitoring.processor import DiscoveryProcessingResult


def _snapshot() -> MonitoringDatabaseSnapshot:
    return MonitoringDatabaseSnapshot(
        documents=10,
        claims=20,
        claim_entity_attributions=20,
        claim_supersessions=1,
        claim_verification_events=2,
        claim_trust_events=0,
        monitor_discoveries=10,
        monitor_runs=5,
        monitor_states=1,
    )


def test_new_ingestion_canary_passes_with_exact_external_deltas() -> None:
    before = _snapshot()
    after = replace(
        before,
        documents=11,
        claims=23,
        claim_entity_attributions=23,
    )
    result = DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=1,
        ingested_count=1,
    )

    decision = assess_auto_ingest_gate_canary(
        before,
        after,
        result,
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=False,
        expected_content_bytes=1234,
        expected_chunk_count=3,
        backblaze_b2_delta=1234,
        qdrant_points_delta=3,
    )

    assert decision.passed
    assert decision.blockers == ()


def test_duplicate_canary_passes_without_external_growth() -> None:
    before = _snapshot()
    result = DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=1,
        duplicate_count=1,
    )

    decision = assess_auto_ingest_gate_canary(
        before,
        before,
        result,
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=False,
        expected_content_bytes=1234,
        expected_chunk_count=3,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert decision.passed


def test_auto_ingest_gate_must_be_enabled() -> None:
    before = _snapshot()
    result = DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=1,
        duplicate_count=1,
    )

    decision = assess_auto_ingest_gate_canary(
        before,
        before,
        result,
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=False,
        trust_promotion_enabled=False,
        expected_content_bytes=1234,
        expected_chunk_count=3,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert not decision.passed
    assert "gate:source_auto_ingest_not_enabled" in decision.blockers


def test_trust_gate_must_remain_disabled() -> None:
    before = _snapshot()
    result = DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=1,
        duplicate_count=1,
    )

    decision = assess_auto_ingest_gate_canary(
        before,
        before,
        result,
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=True,
        expected_content_bytes=1234,
        expected_chunk_count=3,
        backblaze_b2_delta=0,
        qdrant_points_delta=0,
    )

    assert not decision.passed
    assert "gate:trust_promotion_must_remain_disabled" in decision.blockers


def test_new_ingestion_rejects_mismatched_qdrant_growth() -> None:
    before = _snapshot()
    after = replace(before, documents=11)
    result = DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=1,
        ingested_count=1,
    )

    decision = assess_auto_ingest_gate_canary(
        before,
        after,
        result,
        source_monitoring_enabled=True,
        source_auto_ingest_enabled=True,
        trust_promotion_enabled=False,
        expected_content_bytes=1234,
        expected_chunk_count=3,
        backblaze_b2_delta=1234,
        qdrant_points_delta=2,
    )

    assert not decision.passed
    assert "external:qdrant_delta_not_preflight_chunks" in decision.blockers
