from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BatchWriteObservation:
    """Secret-free result for one explicitly controlled queue write."""

    record_id: str
    ingestion_status: str
    queue_status: str
    content_bytes: int
    chunk_count: int
    document_linked: bool
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BoundedBatchWriteDecision:
    passed: bool
    reason: str
    selected_count: int
    ingested_count: int
    duplicate_count: int
    failed_count: int
    rejected_count: int
    expected_backblaze_bytes: int
    expected_qdrant_points: int
    blockers: tuple[str, ...] = ()


def assess_bounded_batch_write(
    observations: tuple[BatchWriteObservation, ...],
    *,
    requested_limit: int,
    max_batch_limit: int = 3,
) -> BoundedBatchWriteDecision:
    """Validate the logical outcome of one small explicit ingestion batch.

    The helper does not authorize scheduling or autonomous ingestion. It only
    validates a batch that an operator explicitly started. New ingestions are
    expected to add their exact preflight byte and chunk counts to B2/Qdrant;
    already-indexed duplicates must add neither. Any failed/rejected item blocks
    the batch from being declared reconciled.
    """
    if requested_limit < 1 or requested_limit > max_batch_limit:
        raise ValueError("requested_limit must be within the controlled batch bound")

    blockers: list[str] = []
    selected_count = len(observations)
    if selected_count != requested_limit:
        blockers.append("processing:selected_count_not_requested_limit")

    record_ids = [item.record_id for item in observations]
    if len(set(record_ids)) != len(record_ids):
        blockers.append("processing:duplicate_record_identity")

    ingested_count = 0
    duplicate_count = 0
    failed_count = 0
    rejected_count = 0
    expected_backblaze_bytes = 0
    expected_qdrant_points = 0

    for item in observations:
        if item.content_bytes < 1:
            blockers.append("processing:invalid_content_bytes")
        if item.chunk_count < 1:
            blockers.append("processing:invalid_chunk_count")

        if item.ingestion_status == "indexed":
            ingested_count += 1
            expected_backblaze_bytes += max(item.content_bytes, 0)
            expected_qdrant_points += max(item.chunk_count, 0)
            if item.queue_status != "ingested":
                blockers.append("queue:indexed_item_status_mismatch")
            if not item.document_linked:
                blockers.append("queue:indexed_item_missing_document_link")
            if item.error_code is not None:
                blockers.append("queue:indexed_item_has_error_code")
        elif item.ingestion_status == "already_indexed":
            duplicate_count += 1
            if item.queue_status != "duplicate":
                blockers.append("queue:duplicate_item_status_mismatch")
            if not item.document_linked:
                blockers.append("queue:duplicate_item_missing_document_link")
            if item.error_code is not None:
                blockers.append("queue:duplicate_item_has_error_code")
        elif item.ingestion_status == "failed":
            failed_count += 1
            blockers.append("processing:failed_item")
        elif item.ingestion_status == "rejected":
            rejected_count += 1
            blockers.append("processing:rejected_item")
        else:
            failed_count += 1
            blockers.append("processing:unexpected_ingestion_status")

    if ingested_count + duplicate_count != selected_count:
        blockers.append("processing:not_all_items_terminal_success")
    if failed_count:
        blockers.append("processing:failed_count_nonzero")
    if rejected_count:
        blockers.append("processing:rejected_count_nonzero")

    unique_blockers = tuple(dict.fromkeys(blockers))
    if unique_blockers:
        return BoundedBatchWriteDecision(
            passed=False,
            reason="bounded_batch_write_not_reconciled",
            selected_count=selected_count,
            ingested_count=ingested_count,
            duplicate_count=duplicate_count,
            failed_count=failed_count,
            rejected_count=rejected_count,
            expected_backblaze_bytes=expected_backblaze_bytes,
            expected_qdrant_points=expected_qdrant_points,
            blockers=unique_blockers,
        )

    return BoundedBatchWriteDecision(
        passed=True,
        reason="bounded_batch_write_reconciled",
        selected_count=selected_count,
        ingested_count=ingested_count,
        duplicate_count=duplicate_count,
        failed_count=failed_count,
        rejected_count=rejected_count,
        expected_backblaze_bytes=expected_backblaze_bytes,
        expected_qdrant_points=expected_qdrant_points,
    )
