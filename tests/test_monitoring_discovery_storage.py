from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.monitoring.discovery import DiscoveredFeedItem
from app.monitoring.discovery_storage import record_discovered_items
from app.monitoring.models import MonitorDefinition
from app.storage.database import Base, SourceMonitorDiscoveryRecord


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


def _item(*, title: str = "Policy update", fingerprint: str = "a" * 64):
    return DiscoveredFeedItem(
        title=title,
        url="https://www.rbi.org.in/press-release/123",
        publication_date=date(2026, 9, 12),
        fingerprint=fingerprint,
    )


def test_new_discovery_creates_pending_queue_record() -> None:
    engine = _engine()
    seen_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        result = record_discovered_items(
            session,
            _monitor(),
            (_item(),),
            seen_at=seen_at,
        )
        record = session.scalar(select(SourceMonitorDiscoveryRecord))

    assert result.created_count == 1
    assert result.existing_count == 0
    assert record is not None
    assert record.status == "pending"
    assert record.document_id is None
    assert record.seen_count == 1
    assert record.url == "https://www.rbi.org.in/press-release/123"


def test_repeat_discovery_is_idempotent_by_monitor_and_url() -> None:
    engine = _engine()
    first_seen = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    second_seen = first_seen + timedelta(hours=1)

    with Session(engine) as session:
        record_discovered_items(
            session,
            _monitor(),
            (_item(),),
            seen_at=first_seen,
        )
        result = record_discovered_items(
            session,
            _monitor(),
            (_item(title="Corrected title", fingerprint="b" * 64),),
            seen_at=second_seen,
        )
        count = session.scalar(select(func.count()).select_from(SourceMonitorDiscoveryRecord))
        record = session.scalar(select(SourceMonitorDiscoveryRecord))

    assert result.created_count == 0
    assert result.existing_count == 1
    assert count == 1
    assert record is not None
    assert record.title == "Corrected title"
    assert record.item_fingerprint == "b" * 64
    assert record.seen_count == 2
    assert record.first_seen_at.replace(tzinfo=UTC) == first_seen
    assert record.last_seen_at.replace(tzinfo=UTC) == second_seen


def test_same_url_in_different_monitors_has_separate_queue_identity() -> None:
    engine = _engine()
    seen_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    second_monitor = MonitorDefinition(
        monitor_id="rbi-secondary-feed",
        source_id="rbi",
        url="https://rbi.org.in/secondary_rss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=10,
    )

    with Session(engine) as session:
        record_discovered_items(session, _monitor(), (_item(),), seen_at=seen_at)
        record_discovered_items(session, second_monitor, (_item(),), seen_at=seen_at)
        records = list(session.scalars(select(SourceMonitorDiscoveryRecord)))

    assert len(records) == 2
    assert {record.monitor_id for record in records} == {
        "rbi-press-releases-rss",
        "rbi-secondary-feed",
    }
