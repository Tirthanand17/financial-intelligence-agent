import pytest

from app.monitoring.batch_processing import (
    BatchWriteObservation,
    assess_bounded_batch_write,
)


def _indexed(record_id: str, *, content_bytes: int = 1000, chunk_count: int = 2):
    return BatchWriteObservation(
        record_id=record_id,
        ingestion_status="indexed",
        queue_status="ingested",
        content_bytes=content_bytes,
        chunk_count=chunk_count,
        document_linked=True,
    )


def _duplicate(record_id: str, *, content_bytes: int = 1000, chunk_count: int = 2):
    return BatchWriteObservation(
        record_id=record_id,
        ingestion_status="already_indexed",
        queue_status="duplicate",
        content_bytes=content_bytes,
        chunk_count=chunk_count,
        document_linked=True,
    )


def test_three_new_items_reconcile_expected_external_growth() -> None:
    decision = assess_bounded_batch_write(
        (
            _indexed("a", content_bytes=100, chunk_count=1),
            _indexed("b", content_bytes=200, chunk_count=2),
            _indexed("c", content_bytes=300, chunk_count=3),
        ),
        requested_limit=3,
    )

    assert decision.passed is True
    assert decision.ingested_count == 3
    assert decision.duplicate_count == 0
    assert decision.expected_backblaze_bytes == 600
    assert decision.expected_qdrant_points == 6


def test_duplicates_do_not_expect_external_growth() -> None:
    decision = assess_bounded_batch_write(
        (_indexed("a", content_bytes=100, chunk_count=1), _duplicate("b")),
        requested_limit=2,
    )

    assert decision.passed is True
    assert decision.ingested_count == 1
    assert decision.duplicate_count == 1
    assert decision.expected_backblaze_bytes == 100
    assert decision.expected_qdrant_points == 1


def test_failed_item_blocks_reconciliation() -> None:
    failed = BatchWriteObservation(
        record_id="b",
        ingestion_status="failed",
        queue_status="pending",
        content_bytes=100,
        chunk_count=1,
        document_linked=False,
        error_code="ingestion_validation_error",
    )
    decision = assess_bounded_batch_write((_indexed("a"), failed), requested_limit=2)

    assert decision.passed is False
    assert "processing:failed_item" in decision.blockers
    assert "processing:not_all_items_terminal_success" in decision.blockers


def test_wrong_queue_status_blocks_reconciliation() -> None:
    item = BatchWriteObservation(
        record_id="a",
        ingestion_status="indexed",
        queue_status="pending",
        content_bytes=100,
        chunk_count=1,
        document_linked=True,
    )
    decision = assess_bounded_batch_write((item,), requested_limit=1)
    assert decision.passed is False
    assert "queue:indexed_item_status_mismatch" in decision.blockers


def test_duplicate_record_identity_is_blocked() -> None:
    decision = assess_bounded_batch_write((_indexed("a"), _duplicate("a")), requested_limit=2)
    assert decision.passed is False
    assert "processing:duplicate_record_identity" in decision.blockers


def test_exact_requested_count_is_required() -> None:
    decision = assess_bounded_batch_write((_indexed("a"),), requested_limit=2)
    assert decision.passed is False
    assert "processing:selected_count_not_requested_limit" in decision.blockers


def test_batch_limit_is_hard_bounded() -> None:
    with pytest.raises(ValueError, match="controlled batch bound"):
        assess_bounded_batch_write((_indexed("a"),), requested_limit=4)
