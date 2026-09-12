from collections.abc import Callable
from datetime import datetime
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.ingestion.downloader import download_trusted_document
from app.monitoring.discovery import discover_feed_items
from app.monitoring.models import (
    CapacityDecision,
    MonitorDefinition,
    MonitorExecutionResult,
    MonitorRunOutcome,
    MonitorState,
)
from app.monitoring.policy import decide_monitor_run
from app.monitoring.storage import record_monitor_run


_XML_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}


class FeedDownload(Protocol):
    content: bytes
    content_type: str


DownloadFeed = Callable[[str, str], FeedDownload]


def _record_and_result(
    session: Session,
    monitor: MonitorDefinition,
    *,
    started_at: datetime,
    finished_at: datetime,
    outcome: MonitorRunOutcome,
    reason: str,
    discovered_count: int = 0,
    rejected_discovery_count: int = 0,
    blocking_services: tuple[str, ...] = (),
    error_code: str | None = None,
) -> MonitorExecutionResult:
    record_monitor_run(
        session,
        monitor,
        started_at=started_at,
        finished_at=finished_at,
        outcome=outcome,
        reason=reason,
        discovered_count=discovered_count,
        blocking_services=blocking_services,
        error_code=error_code,
    )
    return MonitorExecutionResult(
        monitor_id=monitor.monitor_id,
        outcome=outcome,
        reason=reason,
        discovered_count=discovered_count,
        rejected_discovery_count=rejected_discovery_count,
        blocking_services=blocking_services,
        error_code=error_code,
    )


def probe_monitor_once(
    session: Session,
    monitor: MonitorDefinition,
    capacity: CapacityDecision,
    *,
    started_at: datetime,
    finished_at: datetime,
    download_feed: DownloadFeed = download_trusted_document,
) -> MonitorExecutionResult:
    """Run one bounded discovery-only monitor probe.

    Phase 5 begins with observation before autonomous ingestion. This runner can
    fetch only the monitor's explicitly configured allow-listed feed, discover a
    bounded number of allow-listed item URLs, and persist secret-free operational
    telemetry. It never follows or ingests discovered item links.

    Capacity and monitor policy are evaluated before network access. A disabled
    monitor or an unsafe/unknown capacity decision causes a recorded pause and no
    download attempt.
    """
    decision = decide_monitor_run(monitor, capacity)

    if decision.state is MonitorState.DISABLED:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.DISABLED,
            reason="monitor_disabled",
        )

    if decision.state is MonitorState.PAUSED_CAPACITY:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.PAUSED_CAPACITY,
            reason=decision.reason,
            blocking_services=decision.blocking_services,
        )

    try:
        downloaded = download_feed(monitor.source_id, monitor.url)
    except ConnectionError:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            error_code="transient_network_error",
        )
    except httpx.HTTPError:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            error_code="http_error",
        )
    except ValueError:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.FAILED,
            reason="source_policy_rejected",
            error_code="source_policy_rejection",
        )

    content_type = downloaded.content_type.split(";", 1)[0].lower()
    if content_type not in _XML_CONTENT_TYPES:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.FAILED,
            reason="unexpected_feed_content_type",
            error_code="unexpected_feed_content_type",
        )

    try:
        discovery = discover_feed_items(
            downloaded.content,
            source_id=monitor.source_id,
            limit=monitor.max_new_documents_per_run,
        )
    except ValueError:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.FAILED,
            reason="feed_discovery_failed",
            error_code="invalid_feed",
        )

    if not discovery.items:
        return _record_and_result(
            session,
            monitor,
            started_at=started_at,
            finished_at=finished_at,
            outcome=MonitorRunOutcome.NO_CHANGE,
            reason="no_allowlisted_feed_items",
            rejected_discovery_count=discovery.rejected_count,
        )

    return _record_and_result(
        session,
        monitor,
        started_at=started_at,
        finished_at=finished_at,
        outcome=MonitorRunOutcome.SUCCESS,
        reason="discovery_completed",
        discovered_count=len(discovery.items),
        rejected_discovery_count=discovery.rejected_count,
    )
