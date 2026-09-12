from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.monitoring.models import CapacityDecision, MonitorDefinition, MonitorState
from app.monitoring.policy import decide_monitor_run
from app.monitoring.queue_retry import assess_discovery_retry
from app.services.ingestion import ingest_url
from app.sources.registry import validate_source_url
from app.storage.database import SourceMonitorDiscoveryRecord


IngestUrl = Callable[[str, str], dict[str, object]]


@dataclass(frozen=True, slots=True)
class DiscoveryProcessingResult:
    reason: str
    selected_count: int = 0
    ingested_count: int = 0
    duplicate_count: int = 0
    failed_count: int = 0
    rejected_count: int = 0
    blocking_services: tuple[str, ...] = ()


def _mark_attempt(
    record: SourceMonitorDiscoveryRecord,
    *,
    now: datetime,
    error_code: str | None,
) -> None:
    record.attempt_count += 1
    record.last_attempt_at = now
    record.last_error_code = error_code


def _maybe_commit(session: Session, commit: bool) -> None:
    if commit:
        session.commit()


def _process_record(
    session: Session,
    record: SourceMonitorDiscoveryRecord,
    *,
    now: datetime,
    ingest: IngestUrl,
    commit: bool,
) -> DiscoveryProcessingResult:
    try:
        validate_source_url(record.source_id, record.url)
    except ValueError:
        record.status = "rejected"
        _mark_attempt(record, now=now, error_code="source_policy_rejection")
        _maybe_commit(session, commit)
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            rejected_count=1,
        )

    try:
        result = ingest(record.source_id, record.url)
    except ConnectionError:
        _mark_attempt(record, now=now, error_code="transient_network_error")
        _maybe_commit(session, commit)
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )
    except httpx.HTTPError:
        _mark_attempt(record, now=now, error_code="http_error")
        _maybe_commit(session, commit)
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )
    except ValueError:
        _mark_attempt(record, now=now, error_code="ingestion_validation_error")
        _maybe_commit(session, commit)
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )
    except RuntimeError:
        _mark_attempt(record, now=now, error_code="ingestion_runtime_error")
        _maybe_commit(session, commit)
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )

    status = result.get("status")
    document_id = result.get("document_id")
    if status not in {"indexed", "already_indexed"} or not isinstance(document_id, str):
        _mark_attempt(record, now=now, error_code="unexpected_ingestion_result")
        _maybe_commit(session, commit)
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )

    record.document_id = document_id
    record.status = "ingested" if status == "indexed" else "duplicate"
    _mark_attempt(record, now=now, error_code=None)
    _maybe_commit(session, commit)
    return DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=1,
        ingested_count=1 if status == "indexed" else 0,
        duplicate_count=1 if status == "already_indexed" else 0,
    )


def _gate_processing(
    monitor: MonitorDefinition,
    capacity: CapacityDecision,
    *,
    source_monitoring_enabled: bool,
    source_auto_ingest_enabled: bool,
) -> DiscoveryProcessingResult | None:
    if not source_monitoring_enabled:
        return DiscoveryProcessingResult(reason="source_monitoring_disabled")
    if not source_auto_ingest_enabled:
        return DiscoveryProcessingResult(reason="source_auto_ingest_disabled")

    decision = decide_monitor_run(monitor, capacity)
    if decision.state is MonitorState.DISABLED:
        return DiscoveryProcessingResult(reason="monitor_disabled")
    if decision.state is MonitorState.PAUSED_CAPACITY:
        return DiscoveryProcessingResult(
            reason=decision.reason,
            blocking_services=decision.blocking_services,
        )
    return None


def _retry_decision(
    record: SourceMonitorDiscoveryRecord,
    monitor: MonitorDefinition,
    *,
    now: datetime,
):
    return assess_discovery_retry(
        now=now,
        interval_minutes=monitor.interval_minutes,
        attempt_count=record.attempt_count,
        last_attempt_at=record.last_attempt_at,
        last_error_code=record.last_error_code,
    )


def _select_eligible_pending_records(
    session: Session,
    monitor: MonitorDefinition,
    *,
    now: datetime,
    limit: int,
) -> list[SourceMonitorDiscoveryRecord]:
    """Select fresh work first, then only retries whose backoff has expired.

    A failed oldest row must never starve newer untouched discoveries. Fresh rows
    therefore have priority, while failed rows are considered only after their
    per-item retry window is due.
    """
    selected = list(
        session.scalars(
            select(SourceMonitorDiscoveryRecord)
            .where(
                SourceMonitorDiscoveryRecord.monitor_id == monitor.monitor_id,
                SourceMonitorDiscoveryRecord.source_id == monitor.source_id,
                SourceMonitorDiscoveryRecord.status == "pending",
                SourceMonitorDiscoveryRecord.last_error_code.is_(None),
            )
            .order_by(
                SourceMonitorDiscoveryRecord.first_seen_at,
                SourceMonitorDiscoveryRecord.id,
            )
            .limit(limit)
        )
    )
    if len(selected) >= limit:
        return selected

    failed = session.scalars(
        select(SourceMonitorDiscoveryRecord)
        .where(
            SourceMonitorDiscoveryRecord.monitor_id == monitor.monitor_id,
            SourceMonitorDiscoveryRecord.source_id == monitor.source_id,
            SourceMonitorDiscoveryRecord.status == "pending",
            SourceMonitorDiscoveryRecord.last_error_code.is_not(None),
        )
        .order_by(
            SourceMonitorDiscoveryRecord.first_seen_at,
            SourceMonitorDiscoveryRecord.id,
        )
    )
    for record in failed:
        if _retry_decision(record, monitor, now=now).due:
            selected.append(record)
            if len(selected) >= limit:
                break
    return selected


def process_specific_pending_discovery(
    session: Session,
    monitor: MonitorDefinition,
    capacity: CapacityDecision,
    *,
    record_id: str,
    now: datetime,
    source_monitoring_enabled: bool = False,
    source_auto_ingest_enabled: bool = False,
    ingest: IngestUrl = ingest_url,
) -> DiscoveryProcessingResult:
    """Process exactly one named pending queue row behind the normal safety gates.

    The exact-record path also enforces per-item retry backoff. This prevents a
    recurring or recovery worker from repeatedly hitting a failed source item
    before its retry window is eligible.
    """
    blocked = _gate_processing(
        monitor,
        capacity,
        source_monitoring_enabled=source_monitoring_enabled,
        source_auto_ingest_enabled=source_auto_ingest_enabled,
    )
    if blocked is not None:
        return blocked

    record = session.scalar(
        select(SourceMonitorDiscoveryRecord).where(
            SourceMonitorDiscoveryRecord.id == record_id,
            SourceMonitorDiscoveryRecord.monitor_id == monitor.monitor_id,
            SourceMonitorDiscoveryRecord.source_id == monitor.source_id,
            SourceMonitorDiscoveryRecord.status == "pending",
        )
    )
    if record is None:
        return DiscoveryProcessingResult(reason="pending_discovery_not_found")

    retry = _retry_decision(record, monitor, now=now)
    if not retry.due:
        return DiscoveryProcessingResult(reason=retry.reason)

    return _process_record(session, record, now=now, ingest=ingest, commit=True)


def process_pending_discoveries(
    session: Session,
    monitor: MonitorDefinition,
    capacity: CapacityDecision,
    *,
    now: datetime,
    source_monitoring_enabled: bool = False,
    source_auto_ingest_enabled: bool = False,
    limit: int | None = None,
    ingest: IngestUrl = ingest_url,
) -> DiscoveryProcessingResult:
    """Process a bounded pending discovery queue behind explicit safety gates.

    Both global gates must be true, the monitor must be enabled, and cloud
    capacity must be safe. Fresh rows are processed before retries. Failed rows
    remain pending but are excluded until exponential per-item retry backoff has
    expired, preventing repeated source hits and preventing one broken oldest row
    from starving newer queue work.
    """
    blocked = _gate_processing(
        monitor,
        capacity,
        source_monitoring_enabled=source_monitoring_enabled,
        source_auto_ingest_enabled=source_auto_ingest_enabled,
    )
    if blocked is not None:
        return blocked

    effective_limit = monitor.max_new_documents_per_run if limit is None else limit
    if effective_limit < 1 or effective_limit > monitor.max_new_documents_per_run:
        raise ValueError("processing limit must be between 1 and monitor maximum")

    records = _select_eligible_pending_records(
        session,
        monitor,
        now=now,
        limit=effective_limit,
    )
    if not records:
        return DiscoveryProcessingResult(reason="no_eligible_pending_discoveries")

    ingested_count = 0
    duplicate_count = 0
    failed_count = 0
    rejected_count = 0

    for record in records:
        result = _process_record(
            session,
            record,
            now=now,
            ingest=ingest,
            commit=False,
        )
        ingested_count += result.ingested_count
        duplicate_count += result.duplicate_count
        failed_count += result.failed_count
        rejected_count += result.rejected_count

    session.commit()
    return DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=len(records),
        ingested_count=ingested_count,
        duplicate_count=duplicate_count,
        failed_count=failed_count,
        rejected_count=rejected_count,
    )
