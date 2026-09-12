import json
import re
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.monitoring.models import MonitorDefinition, MonitorRunOutcome, MonitorState
from app.storage.database import SourceMonitorRunRecord, SourceMonitorStateRecord


_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _require_safe_code(value: str, field: str) -> str:
    """Accept only symbolic operational codes, never raw exception text."""
    if not _SAFE_CODE_RE.fullmatch(value):
        raise ValueError(f"{field} must be a symbolic non-secret code")
    return value


def _state_for_outcome(outcome: MonitorRunOutcome) -> MonitorState:
    if outcome in {MonitorRunOutcome.SUCCESS, MonitorRunOutcome.NO_CHANGE}:
        return MonitorState.READY
    if outcome is MonitorRunOutcome.PAUSED_CAPACITY:
        return MonitorState.PAUSED_CAPACITY
    if outcome is MonitorRunOutcome.DISABLED:
        return MonitorState.DISABLED
    return MonitorState.PAUSED_ERROR


def record_monitor_run(
    session: Session,
    monitor: MonitorDefinition,
    *,
    started_at: datetime,
    finished_at: datetime,
    outcome: MonitorRunOutcome,
    reason: str,
    discovered_count: int = 0,
    ingested_count: int = 0,
    duplicate_count: int = 0,
    blocking_services: tuple[str, ...] = (),
    error_code: str | None = None,
    last_document_sha256: str | None = None,
    commit: bool = True,
) -> tuple[SourceMonitorStateRecord, SourceMonitorRunRecord]:
    """Append one monitor audit event and update current operational state.

    Raw exception messages, request headers, and credentials are intentionally not
    accepted. `reason` and `error_code` must be symbolic codes suitable for logs.
    """
    _require_safe_code(reason, "reason")
    if error_code is not None:
        _require_safe_code(error_code, "error_code")
    if finished_at < started_at:
        raise ValueError("finished_at cannot be before started_at")
    for value, name in (
        (discovered_count, "discovered_count"),
        (ingested_count, "ingested_count"),
        (duplicate_count, "duplicate_count"),
    ):
        if value < 0:
            raise ValueError(f"{name} cannot be negative")
    if ingested_count + duplicate_count > discovered_count:
        raise ValueError("processed counts cannot exceed discovered_count")
    if last_document_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", last_document_sha256):
        raise ValueError("last_document_sha256 must be lowercase SHA-256")

    run = SourceMonitorRunRecord(
        id=str(uuid4()),
        monitor_id=monitor.monitor_id,
        source_id=monitor.source_id,
        started_at=started_at,
        finished_at=finished_at,
        outcome=outcome.value,
        reason=reason,
        discovered_count=discovered_count,
        ingested_count=ingested_count,
        duplicate_count=duplicate_count,
        blocking_services=json.dumps(sorted(set(blocking_services))),
        error_code=error_code,
    )
    session.add(run)

    state = session.scalar(
        select(SourceMonitorStateRecord).where(
            SourceMonitorStateRecord.monitor_id == monitor.monitor_id
        )
    )
    if state is None:
        state = SourceMonitorStateRecord(
            monitor_id=monitor.monitor_id,
            source_id=monitor.source_id,
            url=monitor.url,
            state=_state_for_outcome(outcome).value,
            reason=reason,
            consecutive_failures=0,
        )
        session.add(state)

    state.source_id = monitor.source_id
    state.url = monitor.url
    state.state = _state_for_outcome(outcome).value
    state.reason = reason
    state.last_checked_at = finished_at

    if outcome in {MonitorRunOutcome.SUCCESS, MonitorRunOutcome.NO_CHANGE}:
        state.last_success_at = finished_at
        state.consecutive_failures = 0
        if last_document_sha256 is not None:
            state.last_document_sha256 = last_document_sha256
    elif outcome is MonitorRunOutcome.FAILED:
        state.consecutive_failures += 1

    if commit:
        session.commit()
        session.refresh(state)
        session.refresh(run)
    else:
        session.flush()

    return state, run
