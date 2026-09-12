from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.monitoring.models import MonitorDefinition, MonitorRunOutcome
from app.monitoring.storage import record_monitor_run
from app.storage.database import Base, SourceMonitorRunRecord, SourceMonitorStateRecord


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _monitor() -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=10,
    )


def test_success_run_updates_state_and_appends_audit() -> None:
    engine = _engine()
    started = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    finished = started + timedelta(seconds=5)
    digest = "a" * 64

    with Session(engine) as session:
        state, run = record_monitor_run(
            session,
            _monitor(),
            started_at=started,
            finished_at=finished,
            outcome=MonitorRunOutcome.SUCCESS,
            reason="ingestion_completed",
            discovered_count=2,
            ingested_count=1,
            duplicate_count=1,
            last_document_sha256=digest,
        )

        assert state.state == "ready"
        assert state.last_checked_at == finished
        assert state.last_success_at == finished
        assert state.last_document_sha256 == digest
        assert state.consecutive_failures == 0
        assert run.outcome == "success"
        assert run.error_code is None


def test_failed_runs_increment_failures_without_storing_raw_exception_text() -> None:
    engine = _engine()
    started = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        for offset in (0, 60):
            record_monitor_run(
                session,
                _monitor(),
                started_at=started + timedelta(minutes=offset),
                finished_at=started + timedelta(minutes=offset, seconds=1),
                outcome=MonitorRunOutcome.FAILED,
                reason="source_download_failed",
                error_code="transient_network_error",
            )

        state = session.scalar(select(SourceMonitorStateRecord))
        runs = list(session.scalars(select(SourceMonitorRunRecord)))

    assert state is not None
    assert state.state == "paused_error"
    assert state.consecutive_failures == 2
    assert len(runs) == 2
    assert {run.error_code for run in runs} == {"transient_network_error"}


def test_capacity_pause_does_not_increment_failure_counter() -> None:
    engine = _engine()
    started = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        record_monitor_run(
            session,
            _monitor(),
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            error_code="transient_network_error",
        )
        state, _ = record_monitor_run(
            session,
            _monitor(),
            started_at=started + timedelta(hours=1),
            finished_at=started + timedelta(hours=1, seconds=1),
            outcome=MonitorRunOutcome.PAUSED_CAPACITY,
            reason="cloud_capacity_low",
            blocking_services=("backblaze_b2",),
        )

    assert state.state == "paused_capacity"
    assert state.consecutive_failures == 1


def test_success_resets_failure_counter() -> None:
    engine = _engine()
    started = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        record_monitor_run(
            session,
            _monitor(),
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            outcome=MonitorRunOutcome.FAILED,
            reason="source_download_failed",
            error_code="transient_network_error",
        )
        state, _ = record_monitor_run(
            session,
            _monitor(),
            started_at=started + timedelta(hours=1),
            finished_at=started + timedelta(hours=1, seconds=1),
            outcome=MonitorRunOutcome.NO_CHANGE,
            reason="no_new_evidence",
        )

    assert state.state == "ready"
    assert state.consecutive_failures == 0


def test_raw_error_text_is_rejected_from_observability_fields() -> None:
    engine = _engine()
    started = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        with pytest.raises(ValueError, match="symbolic non-secret code"):
            record_monitor_run(
                session,
                _monitor(),
                started_at=started,
                finished_at=started + timedelta(seconds=1),
                outcome=MonitorRunOutcome.FAILED,
                reason="connection failed for https://user:secret@example.test",
                error_code="network_error",
            )


def test_counts_cannot_claim_more_processed_than_discovered() -> None:
    engine = _engine()
    started = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        with pytest.raises(ValueError, match="cannot exceed"):
            record_monitor_run(
                session,
                _monitor(),
                started_at=started,
                finished_at=started + timedelta(seconds=1),
                outcome=MonitorRunOutcome.SUCCESS,
                reason="ingestion_completed",
                discovered_count=1,
                ingested_count=1,
                duplicate_count=1,
            )


def test_run_history_is_append_only_while_state_is_single_row() -> None:
    engine = _engine()
    started = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        for hour in range(3):
            record_monitor_run(
                session,
                _monitor(),
                started_at=started + timedelta(hours=hour),
                finished_at=started + timedelta(hours=hour, seconds=1),
                outcome=MonitorRunOutcome.NO_CHANGE,
                reason="no_new_evidence",
            )

        state_count = session.scalar(
            select(func.count()).select_from(SourceMonitorStateRecord)
        )
        run_count = session.scalar(
            select(func.count()).select_from(SourceMonitorRunRecord)
        )

    assert state_count == 1
    assert run_count == 3
