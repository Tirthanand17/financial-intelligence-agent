from dataclasses import replace

from app.monitoring.soak_readiness import (
    ReadOnlySoakSample,
    assess_read_only_soak,
)


def _sample() -> ReadOnlySoakSample:
    return ReadOnlySoakSample(
        documents=11,
        claims=37,
        verification_events=0,
        trust_events=0,
        discoveries=40,
        monitor_runs=8,
        monitor_states=4,
        backblaze_b2_bytes=2448214,
        qdrant_points=31,
        capacity_allows_ingestion=True,
        rss_bytes=100_000_000,
    )


def test_stable_samples_pass() -> None:
    decision = assess_read_only_soak(
        (_sample(), replace(_sample(), rss_bytes=101_000_000)),
        max_rss_growth_bytes=64 * 1024 * 1024,
    )
    assert decision.passed
    assert decision.blockers == ()


def test_storage_or_row_count_drift_fails() -> None:
    drifted = replace(
        _sample(),
        documents=12,
        backblaze_b2_bytes=2449000,
        qdrant_points=32,
    )
    decision = assess_read_only_soak(
        (_sample(), drifted),
        max_rss_growth_bytes=64 * 1024 * 1024,
    )
    assert not decision.passed
    assert "soak:documents_changed" in decision.blockers
    assert "soak:backblaze_b2_bytes_changed" in decision.blockers
    assert "soak:qdrant_points_changed" in decision.blockers


def test_capacity_or_memory_growth_fails() -> None:
    degraded = replace(
        _sample(),
        capacity_allows_ingestion=False,
        rss_bytes=180_000_000,
    )
    decision = assess_read_only_soak(
        (_sample(), degraded),
        max_rss_growth_bytes=64 * 1024 * 1024,
    )
    assert not decision.passed
    assert "soak:capacity_not_safe" in decision.blockers
    assert "soak:rss_growth_exceeded" in decision.blockers
