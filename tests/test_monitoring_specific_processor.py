from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.monitoring.capacity import evaluate_capacity
from app.monitoring.discovery import DiscoveredFeedItem
from app.monitoring.discovery_storage import record_discovered_items
from app.monitoring.models import CapacityState, MonitorDefinition, ServiceCapacity
from app.monitoring.processor import process_specific_pending_discovery
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


def _capacity():
    return evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.OK),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )


def _queue(session: Session, monitor: MonitorDefinition) -> list[SourceMonitorDiscoveryRecord]:
    seen_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    items = (
        DiscoveredFeedItem(
            title="One",
            url="https://www.rbi.org.in/press-release/1",
            publication_date=None,
            fingerprint="1" * 64,
        ),
        DiscoveredFeedItem(
            title="Two",
            url="https://www.rbi.org.in/press-release/2",
            publication_date=None,
            fingerprint="2" * 64,
        ),
    )
    record_discovered_items(session, monitor, items, seen_at=seen_at)
    return list(
        session.scalars(
            select(SourceMonitorDiscoveryRecord).order_by(SourceMonitorDiscoveryRecord.url)
        )
    )


def test_specific_processor_only_mutates_named_pending_record() -> None:
    engine = _engine()
    monitor = _monitor()

    with Session(engine) as session:
        records = _queue(session, monitor)
        target = records[1]
        other = records[0]

        result = process_specific_pending_discovery(
            session,
            monitor,
            _capacity(),
            record_id=target.id,
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=lambda *_: {
                "status": "indexed",
                "document_id": "11111111-1111-1111-1111-111111111111",
            },
        )
        session.refresh(target)
        session.refresh(other)

    assert result.selected_count == 1
    assert result.ingested_count == 1
    assert target.status == "ingested"
    assert target.attempt_count == 1
    assert other.status == "pending"
    assert other.attempt_count == 0


def test_specific_processor_missing_record_does_not_process_another_row() -> None:
    engine = _engine()
    monitor = _monitor()
    calls = 0

    def ingest(*_):
        nonlocal calls
        calls += 1
        raise AssertionError("ingestion must not run")

    with Session(engine) as session:
        records = _queue(session, monitor)
        result = process_specific_pending_discovery(
            session,
            monitor,
            _capacity(),
            record_id="00000000-0000-0000-0000-000000000000",
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=ingest,
        )
        refreshed = list(
            session.scalars(
                select(SourceMonitorDiscoveryRecord).order_by(SourceMonitorDiscoveryRecord.url)
            )
        )

    assert calls == 0
    assert result.reason == "pending_discovery_not_found"
    assert result.selected_count == 0
    assert all(record.status == "pending" for record in refreshed)
    assert all(record.attempt_count == 0 for record in refreshed)
