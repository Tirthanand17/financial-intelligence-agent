from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.monitoring.models import CapacityDecision, MonitorDefinition, MonitorState
from app.monitoring.policy import decide_monitor_run
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


def _process_record(
    session: Session,
    record: SourceMonitorDiscoveryRecord,
    *,
    now: datetime,
    ingest: IngestUrl,
) -> DiscoveryProcessingResult:
    try:
        validate_source_url(record.source_id, record.url)
    except ValueError:
        record.status = "rejected"
        _mark_attempt(record, now=now, error_code="source_policy_rejection")
        session.commit()
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            rejected_count=1,
        )

    try:
        result = ingest(record.source_id, record.url)
    except ConnectionError:
        _mark_attempt(record, now=now, error_code="transient_network_error")
        session.commit()
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )
    except httpx.HTTPError:
        _mark_attempt(record, now=now, error_code="http_error")
        session.commit()
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )
    except ValueError:
        _mark_attempt(record, now=now, error_code="ingestion_validation_error")
        session.commit()
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )
    except RuntimeError:
        _mark_attempt(record, now=now, error_code="ingestion_runtime_error")
        session.commit()
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )

    status = result.get("status")
    document_id = result.get("document_id")
    if status not in {"indexed", "already_indexed"} or not isinstance(document_id, str):
        _mark_attempt(record, now=now, error_code="unexpected_ingestion_result")
        session.commit()
        return DiscoveryProcessingResult(
            reason="processing_completed",
            selected_count=1,
            failed_count=1,
        )

    record.document_id = document_id
    record.status = "ingested" if status == "indexed" else "duplicate"
    _mark_attempt(record, now=now, error_code=None)
    session.commit()
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

    This exact-record entry point exists for controlled canaries and recovery work
    where selecting a different pending row would violate the approved write
    boundary. It does not weaken source policy, capacity policy, or the two global
    monitoring/auto-ingest gates.
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

    return _process_record(session, record, now=now, ingest=ingest)


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
    """Process a bounded pending discovery queue behind two explicit gates.

    Feed monitoring and link ingestion are intentionally independent. Both gates
    must be true, the monitor must be enabled, and cloud capacity must be safe.
    Each queued URL is re-validated against the source allow-list immediately
    before calling the existing trusted ingestion pipeline.

    Operational failures persist only symbolic error codes. Failed items remain
    pending for a later retry; policy-rejected URLs are terminally marked rejected.
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

    records = list(
        session.scalars(
            select(SourceMonitorDiscoveryRecord)
            .where(
                SourceMonitorDiscoveryRecord.monitor_id == monitor.monitor_id,
                SourceMonitorDiscoveryRecord.source_id == monitor.source_id,
                SourceMonitorDiscoveryRecord.status == "pending",
            )
            .order_by(
                SourceMonitorDiscoveryRecord.first_seen_at,
                SourceMonitorDiscoveryRecord.id,
            )
            .limit(effective_limit)
        )
    )

    ingested_count = 0
    duplicate_count = 0
    failed_count = 0
    rejected_count = 0

    for record in records:
        result = _process_record(session, record, now=now, ingest=ingest)
        ingested_count += result.ingested_count
        duplicate_count += result.duplicate_count
        failed_count += result.failed_count
        rejected_count += result.rejected_count

    return DiscoveryProcessingResult(
        reason="processing_completed",
        selected_count=len(records),
        ingested_count=ingested_count,
        duplicate_count=duplicate_count,
        failed_count=failed_count,
        rejected_count=rejected_count,
    )
