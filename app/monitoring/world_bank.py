from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from app.monitoring.models import CapacityDecision, MonitorDefinition, MonitorRunOutcome
from app.monitoring.scheduled_gate import assess_scheduled_monitor_gate
from app.monitoring.storage import record_monitor_run
from app.services.world_bank_live_canary import (
    WorldBankLiveDownload,
    download_world_bank_live_payload,
)
from app.services.world_bank_persistence import (
    WorldBankPersistenceResult,
    persist_world_bank_payload,
)
from app.sources.world_bank import build_world_bank_indicator_url
from app.storage.database import SourceMonitorStateRecord


WORLD_BANK_OPERATIONAL_MONITOR_ID = "world-bank-india-gdp-api"
WORLD_BANK_OPERATIONAL_INDICATOR = "NY.GDP.MKTP.KD.ZG"
WORLD_BANK_OPERATIONAL_RECENT_OBSERVATIONS = 3
WORLD_BANK_OPERATIONAL_INTERVAL_MINUTES = 24 * 60
WORLD_BANK_OPERATIONAL_CONFIRMATION = "WORLD_BANK_OPERATIONAL_CANARY"


@dataclass(frozen=True, slots=True)
class WorldBankOperationalResult:
    monitor_id: str
    outcome: MonitorRunOutcome
    reason: str
    performed: bool
    status: str | None = None
    sha256: str | None = None
    document_id: str | None = None
    chunk_count: int = 0
    claim_count: int = 0
    observation_periods: tuple[str, ...] = ()
    blocking_services: tuple[str, ...] = ()


DownloadWorldBank = Callable[..., WorldBankLiveDownload]
PersistWorldBank = Callable[..., WorldBankPersistenceResult]
CapacityCheck = Callable[[], CapacityDecision]
RecordMonitorRun = Callable[..., object]


def build_world_bank_operational_monitor(*, enabled: bool = True) -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id=WORLD_BANK_OPERATIONAL_MONITOR_ID,
        source_id="world_bank",
        url=build_world_bank_indicator_url(
            WORLD_BANK_OPERATIONAL_INDICATOR,
            recent_observations=WORLD_BANK_OPERATIONAL_RECENT_OBSERVATIONS,
        ),
        interval_minutes=WORLD_BANK_OPERATIONAL_INTERVAL_MINUTES,
        enabled=enabled,
        max_new_documents_per_run=1,
    )


def _record(
    session: Session,
    monitor: MonitorDefinition,
    *,
    started_at: datetime,
    outcome: MonitorRunOutcome,
    reason: str,
    discovered_count: int = 0,
    ingested_count: int = 0,
    duplicate_count: int = 0,
    blocking_services: tuple[str, ...] = (),
    error_code: str | None = None,
    last_document_sha256: str | None = None,
    record_run: RecordMonitorRun = record_monitor_run,
) -> None:
    record_run(
        session,
        monitor,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        outcome=outcome,
        reason=reason,
        discovered_count=discovered_count,
        ingested_count=ingested_count,
        duplicate_count=duplicate_count,
        blocking_services=blocking_services,
        error_code=error_code,
        last_document_sha256=last_document_sha256,
        commit=True,
    )


def run_world_bank_operational_once(
    session: Session,
    monitor: MonitorDefinition,
    capacity_before: CapacityDecision,
    *,
    now: datetime,
    source_monitoring_enabled: bool = False,
    source_auto_ingest_enabled: bool = False,
    trust_promotion_enabled: bool = False,
    allow_network: bool = False,
    allow_write: bool = False,
    download: DownloadWorldBank = download_world_bank_live_payload,
    persist: PersistWorldBank = persist_world_bank_payload,
    capacity_after: CapacityCheck,
    record_run: RecordMonitorRun = record_monitor_run,
) -> WorldBankOperationalResult:
    """Run one due, bounded World Bank evidence cycle using the validated JSON path.

    This source-specific monitor deliberately bypasses the generic document-URL
    queue because World Bank annual observations have a separate exact-byte and
    temporal contract. At most one JSON evidence document is handled per due
    cycle; no structured claim is permitted by this monitor.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if monitor.monitor_id != WORLD_BANK_OPERATIONAL_MONITOR_ID:
        raise ValueError("Unexpected World Bank operational monitor id")
    if monitor.source_id != "world_bank":
        raise ValueError("World Bank operational monitor source mismatch")
    if monitor.max_new_documents_per_run != 1:
        raise ValueError("World Bank operational monitor must remain one-document bounded")
    if not allow_network or not allow_write:
        raise RuntimeError("WORLD_BANK_OPERATIONAL_REQUIRES_NETWORK_AND_WRITE_FLAGS")
    if not source_monitoring_enabled:
        raise RuntimeError("WORLD_BANK_OPERATIONAL_SOURCE_MONITORING_DISABLED")
    if not source_auto_ingest_enabled:
        raise RuntimeError("WORLD_BANK_OPERATIONAL_AUTO_INGEST_DISABLED")
    if trust_promotion_enabled:
        raise RuntimeError("WORLD_BANK_OPERATIONAL_TRUST_PROMOTION_MUST_REMAIN_DISABLED")

    state = session.get(SourceMonitorStateRecord, monitor.monitor_id)
    gate = assess_scheduled_monitor_gate(
        monitor,
        now=now,
        last_checked_at=state.last_checked_at if state is not None else None,
        consecutive_failures=state.consecutive_failures if state is not None else 0,
    )
    if not gate.due:
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.NO_CHANGE,
            reason=gate.reason,
            performed=False,
        )

    if not capacity_before.allow_ingestion:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.PAUSED_CAPACITY,
            reason="capacity_blocked",
            blocking_services=capacity_before.blocking_services,
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.PAUSED_CAPACITY,
            reason="capacity_blocked",
            performed=False,
            blocking_services=capacity_before.blocking_services,
        )

    try:
        downloaded = download(
            WORLD_BANK_OPERATIONAL_INDICATOR,
            recent_observations=WORLD_BANK_OPERATIONAL_RECENT_OBSERVATIONS,
        )
    except ConnectionError:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            error_code="transient_network_error",
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            performed=False,
        )
    except httpx.HTTPError:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            error_code="http_error",
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            performed=False,
        )
    except ValueError:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_validation_failed",
            error_code="source_policy_rejection",
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_validation_failed",
            performed=False,
        )

    try:
        persisted = persist(
            content=downloaded.content,
            indicator_code=WORLD_BANK_OPERATIONAL_INDICATOR,
            source_url=downloaded.source_url,
            final_url=downloaded.final_url,
            recent_observations=WORLD_BANK_OPERATIONAL_RECENT_OBSERVATIONS,
            retrieved_at=downloaded.retrieved_at,
            expected_sha256=downloaded.sha256,
        )
    except ValueError:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="persistence_validation_failed",
            error_code="persistence_validation_error",
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.FAILED,
            reason="persistence_validation_failed",
            performed=True,
        )
    except RuntimeError:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="persistence_reconciliation_failed",
            error_code="persistence_reconciliation_error",
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.FAILED,
            reason="persistence_reconciliation_failed",
            performed=True,
        )

    if persisted.status not in {"indexed", "already_indexed"} or persisted.claim_count != 0:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="unexpected_persistence_result",
            discovered_count=1,
            error_code="unexpected_persistence_result",
            last_document_sha256=persisted.sha256,
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.FAILED,
            reason="unexpected_persistence_result",
            performed=True,
            status=persisted.status,
            sha256=persisted.sha256,
            document_id=persisted.document_id,
            chunk_count=persisted.chunk_count,
            claim_count=persisted.claim_count,
            observation_periods=persisted.observation_periods,
        )

    try:
        after = capacity_after()
    except Exception:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="post_write_capacity_unknown",
            discovered_count=1,
            ingested_count=1 if persisted.status == "indexed" else 0,
            duplicate_count=1 if persisted.status == "already_indexed" else 0,
            error_code="capacity_measurement_failed",
            last_document_sha256=persisted.sha256,
            record_run=record_run,
        )
        raise RuntimeError("WORLD_BANK_OPERATIONAL_POST_WRITE_CAPACITY_UNKNOWN") from None

    if not after.allow_ingestion:
        _record(
            session,
            monitor,
            started_at=now,
            outcome=MonitorRunOutcome.FAILED,
            reason="post_write_capacity_unsafe",
            discovered_count=1,
            ingested_count=1 if persisted.status == "indexed" else 0,
            duplicate_count=1 if persisted.status == "already_indexed" else 0,
            blocking_services=after.blocking_services,
            error_code="capacity_blocked_after_write",
            last_document_sha256=persisted.sha256,
            record_run=record_run,
        )
        return WorldBankOperationalResult(
            monitor_id=monitor.monitor_id,
            outcome=MonitorRunOutcome.FAILED,
            reason="post_write_capacity_unsafe",
            performed=True,
            status=persisted.status,
            sha256=persisted.sha256,
            document_id=persisted.document_id,
            chunk_count=persisted.chunk_count,
            claim_count=persisted.claim_count,
            observation_periods=persisted.observation_periods,
            blocking_services=after.blocking_services,
        )

    outcome = (
        MonitorRunOutcome.SUCCESS
        if persisted.status == "indexed"
        else MonitorRunOutcome.NO_CHANGE
    )
    reason = (
        "world_bank_evidence_indexed"
        if persisted.status == "indexed"
        else "world_bank_evidence_unchanged"
    )
    _record(
        session,
        monitor,
        started_at=now,
        outcome=outcome,
        reason=reason,
        discovered_count=1,
        ingested_count=1 if persisted.status == "indexed" else 0,
        duplicate_count=1 if persisted.status == "already_indexed" else 0,
        last_document_sha256=persisted.sha256,
        record_run=record_run,
    )
    return WorldBankOperationalResult(
        monitor_id=monitor.monitor_id,
        outcome=outcome,
        reason=reason,
        performed=True,
        status=persisted.status,
        sha256=persisted.sha256,
        document_id=persisted.document_id,
        chunk_count=persisted.chunk_count,
        claim_count=persisted.claim_count,
        observation_periods=persisted.observation_periods,
    )
