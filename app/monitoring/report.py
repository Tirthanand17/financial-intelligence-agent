from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.database import (
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
    SourceMonitorStateRecord,
)


@dataclass(frozen=True, slots=True)
class MonitoringStatusReport:
    source_monitoring_enabled: bool
    source_auto_ingest_enabled: bool
    monitor_state_counts: tuple[tuple[str, int], ...]
    run_outcome_counts: tuple[tuple[str, int], ...]
    discovery_status_counts: tuple[tuple[str, int], ...]
    total_monitor_states: int
    total_runs: int
    total_discoveries: int
    pending_discoveries: int


def _counts(values: list[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def build_monitoring_status_report(
    session: Session,
    *,
    source_monitoring_enabled: bool,
    source_auto_ingest_enabled: bool,
) -> MonitoringStatusReport:
    """Build a read-only, secret-free Phase 5 operational summary.

    The report only reads persisted monitoring metadata. It performs no network
    calls, does not run monitors, does not process discoveries, and never exposes
    credentials or provider connection details.
    """
    states = list(session.scalars(select(SourceMonitorStateRecord)))
    runs = list(session.scalars(select(SourceMonitorRunRecord)))
    discoveries = list(session.scalars(select(SourceMonitorDiscoveryRecord)))

    state_counts = _counts([record.state for record in states])
    run_counts = _counts([record.outcome for record in runs])
    discovery_counts = _counts([record.status for record in discoveries])
    pending = sum(record.status == "pending" for record in discoveries)

    return MonitoringStatusReport(
        source_monitoring_enabled=source_monitoring_enabled,
        source_auto_ingest_enabled=source_auto_ingest_enabled,
        monitor_state_counts=state_counts,
        run_outcome_counts=run_counts,
        discovery_status_counts=discovery_counts,
        total_monitor_states=len(states),
        total_runs=len(runs),
        total_discoveries=len(discoveries),
        pending_discoveries=pending,
    )
