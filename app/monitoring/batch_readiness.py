from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class BatchPreflightObservation:
    """Secret-free result for one queued document validated in memory."""

    record_id: str
    passed: bool
    error_code: str | None = None
    content_bytes: int | None = None
    chunk_count: int | None = None
    eligible_claim_count: int | None = None
    publication_date: date | None = None


@dataclass(frozen=True, slots=True)
class BatchReadinessDecision:
    ready: bool
    reason: str
    selected_count: int
    passed_count: int
    failed_count: int
    total_content_bytes: int
    blockers: tuple[str, ...] = ()


def assess_batch_preflight(
    observations: tuple[BatchPreflightObservation, ...],
    *,
    requested_limit: int,
    max_canary_limit: int = 3,
    max_total_content_bytes: int = 5 * 1024 * 1024,
) -> BatchReadinessDecision:
    """Decide whether a small read-only queue sample is safe for the next phase.

    Phase 8 begins with a canary sample rather than enabling scheduled ingestion.
    Every selected item must pass the existing trusted preflight path, retain an
    explicit publication date, and fit inside a deliberately small aggregate byte
    bound. No requirement is placed on structured-claim count because useful
    primary-source evidence can legitimately contain zero currently extractable
    scalar claims.
    """
    if requested_limit < 1 or requested_limit > max_canary_limit:
        raise ValueError("requested_limit must be within the Phase 8 canary bound")
    if max_total_content_bytes < 1:
        raise ValueError("max_total_content_bytes must be positive")

    blockers: list[str] = []
    selected_count = len(observations)
    if selected_count == 0:
        blockers.append("queue:no_pending_items")
    if selected_count > requested_limit:
        blockers.append("queue:selected_count_exceeds_request")

    record_ids = [item.record_id for item in observations]
    if len(set(record_ids)) != len(record_ids):
        blockers.append("queue:duplicate_record_identity")

    passed_count = 0
    failed_count = 0
    total_content_bytes = 0

    for item in observations:
        if not item.passed:
            failed_count += 1
            blockers.append("preflight:item_failed")
            if not item.error_code:
                blockers.append("preflight:failed_item_missing_error_code")
            continue

        passed_count += 1
        if item.error_code is not None:
            blockers.append("preflight:passed_item_has_error_code")
        if item.content_bytes is None or item.content_bytes <= 0:
            blockers.append("preflight:invalid_content_size")
        else:
            total_content_bytes += item.content_bytes
        if item.chunk_count is None or item.chunk_count < 1:
            blockers.append("preflight:no_searchable_chunks")
        if item.eligible_claim_count is None or item.eligible_claim_count < 0:
            blockers.append("preflight:invalid_claim_count")
        if item.publication_date is None:
            blockers.append("preflight:missing_publication_date")

    if failed_count:
        blockers.append("preflight:not_all_items_passed")
    if total_content_bytes > max_total_content_bytes:
        blockers.append("preflight:aggregate_content_bound_exceeded")

    unique_blockers = tuple(dict.fromkeys(blockers))
    if unique_blockers:
        return BatchReadinessDecision(
            ready=False,
            reason="batch_preflight_not_ready",
            selected_count=selected_count,
            passed_count=passed_count,
            failed_count=failed_count,
            total_content_bytes=total_content_bytes,
            blockers=unique_blockers,
        )

    return BatchReadinessDecision(
        ready=True,
        reason="batch_preflight_ready",
        selected_count=selected_count,
        passed_count=passed_count,
        failed_count=failed_count,
        total_content_bytes=total_content_bytes,
    )
