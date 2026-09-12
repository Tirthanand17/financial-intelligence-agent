from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.monitoring.report import build_monitoring_status_report
from app.storage.database import (
    Base,
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
    SourceMonitorStateRecord,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_empty_report_is_safe_and_read_only() -> None:
    engine = _engine()

    with Session(engine) as session:
        report = build_monitoring_status_report(
            session,
            source_monitoring_enabled=False,
            source_auto_ingest_enabled=False,
        )

    assert report.source_monitoring_enabled is False
    assert report.source_auto_ingest_enabled is False
    assert report.total_monitor_states == 0
    assert report.total_runs == 0
    assert report.total_discoveries == 0
    assert report.pending_discoveries == 0
    assert report.monitor_state_counts == ()
    assert report.run_outcome_counts == ()
    assert report.discovery_status_counts == ()


def test_report_counts_persisted_monitoring_metadata_without_mutation() -> None:
    engine = _engine()
    now = datetime(2026, 9, 12, 11, 0, tzinfo=UTC)

    with Session(engine) as session:
        session.add(
            SourceMonitorStateRecord(
                monitor_id="rbi-press-releases-rss",
                source_id="rbi",
                url="https://rbi.org.in/pressreleases_rss.xml",
                state="ready",
                reason="discovery_completed",
                last_checked_at=now,
                last_success_at=now,
                last_document_sha256=None,
                consecutive_failures=0,
            )
        )
        for outcome in ("success", "success", "failed"):
            session.add(
                SourceMonitorRunRecord(
                    id=str(uuid4()),
                    monitor_id="rbi-press-releases-rss",
                    source_id="rbi",
                    started_at=now,
                    finished_at=now,
                    outcome=outcome,
                    reason="test_event",
                    discovered_count=0,
                    ingested_count=0,
                    duplicate_count=0,
                    blocking_services="[]",
                    error_code=None,
                )
            )
        for status in ("pending", "pending", "ingested", "duplicate", "rejected"):
            session.add(
                SourceMonitorDiscoveryRecord(
                    id=str(uuid4()),
                    discovery_key=uuid4().hex + uuid4().hex,
                    item_fingerprint=uuid4().hex + uuid4().hex,
                    monitor_id="rbi-press-releases-rss",
                    source_id="rbi",
                    url=f"https://www.rbi.org.in/{uuid4()}",
                    title="Test",
                    publication_date=None,
                    status=status,
                    document_id=None,
                    first_seen_at=now,
                    last_seen_at=now,
                    seen_count=1,
                    attempt_count=0,
                    last_attempt_at=None,
                    last_error_code=None,
                )
            )
        session.commit()

        report = build_monitoring_status_report(
            session,
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=False,
        )
        state_count_after = session.scalar(
            select(func.count()).select_from(SourceMonitorStateRecord)
        )
        run_count_after = session.scalar(
            select(func.count()).select_from(SourceMonitorRunRecord)
        )
        discovery_count_after = session.scalar(
            select(func.count()).select_from(SourceMonitorDiscoveryRecord)
        )

    assert report.monitor_state_counts == (("ready", 1),)
    assert report.run_outcome_counts == (("failed", 1), ("success", 2))
    assert report.discovery_status_counts == (
        ("duplicate", 1),
        ("ingested", 1),
        ("pending", 2),
        ("rejected", 1),
    )
    assert report.total_monitor_states == 1
    assert report.total_runs == 3
    assert report.total_discoveries == 5
    assert report.pending_discoveries == 2
    assert state_count_after == 1
    assert run_count_after == 3
    assert discovery_count_after == 5
