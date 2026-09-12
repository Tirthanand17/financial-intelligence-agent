from datetime import date

import pytest

from app.monitoring.batch_readiness import (
    BatchPreflightObservation,
    assess_batch_preflight,
)


def _passed(record_id: str, *, content_bytes: int = 120_000) -> BatchPreflightObservation:
    return BatchPreflightObservation(
        record_id=record_id,
        passed=True,
        content_bytes=content_bytes,
        chunk_count=3,
        eligible_claim_count=0,
        publication_date=date(2026, 9, 11),
    )


def test_batch_readiness_accepts_three_small_dated_preflights() -> None:
    decision = assess_batch_preflight(
        (_passed("a"), _passed("b"), _passed("c")),
        requested_limit=3,
    )

    assert decision.ready is True
    assert decision.reason == "batch_preflight_ready"
    assert decision.selected_count == 3
    assert decision.passed_count == 3
    assert decision.failed_count == 0
    assert decision.blockers == ()


def test_batch_readiness_allows_zero_structured_claims() -> None:
    decision = assess_batch_preflight((_passed("a"),), requested_limit=1)
    assert decision.ready is True


def test_batch_readiness_rejects_failed_item() -> None:
    failed = BatchPreflightObservation(
        record_id="b",
        passed=False,
        error_code="preflight_validation_error",
    )
    decision = assess_batch_preflight((_passed("a"), failed), requested_limit=2)

    assert decision.ready is False
    assert decision.failed_count == 1
    assert "preflight:item_failed" in decision.blockers
    assert "preflight:not_all_items_passed" in decision.blockers


def test_batch_readiness_rejects_missing_publication_date() -> None:
    item = BatchPreflightObservation(
        record_id="a",
        passed=True,
        content_bytes=100,
        chunk_count=1,
        eligible_claim_count=2,
        publication_date=None,
    )
    decision = assess_batch_preflight((item,), requested_limit=1)

    assert decision.ready is False
    assert "preflight:missing_publication_date" in decision.blockers


def test_batch_readiness_rejects_duplicate_queue_identity() -> None:
    decision = assess_batch_preflight((_passed("a"), _passed("a")), requested_limit=2)
    assert decision.ready is False
    assert "queue:duplicate_record_identity" in decision.blockers


def test_batch_readiness_rejects_aggregate_byte_overflow() -> None:
    decision = assess_batch_preflight(
        (_passed("a", content_bytes=3_000_000), _passed("b", content_bytes=3_000_000)),
        requested_limit=2,
        max_total_content_bytes=5_000_000,
    )
    assert decision.ready is False
    assert "preflight:aggregate_content_bound_exceeded" in decision.blockers


def test_batch_readiness_rejects_empty_queue() -> None:
    decision = assess_batch_preflight((), requested_limit=1)
    assert decision.ready is False
    assert "queue:no_pending_items" in decision.blockers


def test_batch_readiness_limit_is_hard_bounded() -> None:
    with pytest.raises(ValueError, match="canary bound"):
        assess_batch_preflight((_passed("a"),), requested_limit=4)
