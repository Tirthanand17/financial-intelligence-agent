from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.monitoring.capacity import evaluate_capacity
from app.monitoring.discovery import DiscoveredFeedItem
from app.monitoring.discovery_storage import record_discovered_items
from app.monitoring.models import CapacityState, MonitorDefinition, ServiceCapacity
from app.monitoring.processor import process_pending_discoveries
from app.storage.database import Base, SourceMonitorDiscoveryRecord


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _monitor(*, max_new_documents_per_run: int = 2) -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=max_new_documents_per_run,
    )


def _safe_capacity():
    return evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.OK),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )


def _queue(session: Session, monitor: MonitorDefinition, *, count: int = 1) -> None:
    seen_at = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    items = tuple(
        DiscoveredFeedItem(
            title=f"Item {index}",
            url=f"https://www.rbi.org.in/press-release/{index}",
            publication_date=None,
            fingerprint=f"{index:064x}",
        )
        for index in range(1, count + 1)
    )
    record_discovered_items(session, monitor, items, seen_at=seen_at)


def test_both_global_gates_must_be_enabled_before_ingestion() -> None:
    engine = _engine()
    monitor = _monitor()
    calls = 0

    def ingest(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("ingestion must not run")

    with Session(engine) as session:
        _queue(session, monitor)
        first = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            ingest=ingest,
        )
        second = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            ingest=ingest,
        )
        record = session.scalar(select(SourceMonitorDiscoveryRecord))

    assert calls == 0
    assert first.reason == "source_monitoring_disabled"
    assert second.reason == "source_auto_ingest_disabled"
    assert record is not None and record.status == "pending"
    assert record.attempt_count == 0


def test_capacity_pause_happens_before_ingestion() -> None:
    engine = _engine()
    monitor = _monitor()
    calls = 0
    capacity = evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.LOW),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )

    def ingest(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("ingestion must not run")

    with Session(engine) as session:
        _queue(session, monitor)
        result = process_pending_discoveries(
            session,
            monitor,
            capacity,
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=ingest,
        )

    assert calls == 0
    assert result.reason == "cloud_capacity_low"
    assert result.blocking_services == ("backblaze_b2",)


def test_successful_processing_marks_discovery_ingested() -> None:
    engine = _engine()
    monitor = _monitor()

    with Session(engine) as session:
        _queue(session, monitor)
        result = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=lambda *_: {
                "status": "indexed",
                "document_id": "11111111-1111-1111-1111-111111111111",
            },
        )
        record = session.scalar(select(SourceMonitorDiscoveryRecord))

    assert result.selected_count == 1
    assert result.ingested_count == 1
    assert result.duplicate_count == 0
    assert result.failed_count == 0
    assert record is not None
    assert record.status == "ingested"
    assert record.document_id == "11111111-1111-1111-1111-111111111111"
    assert record.attempt_count == 1
    assert record.last_error_code is None


def test_already_indexed_result_marks_discovery_duplicate() -> None:
    engine = _engine()
    monitor = _monitor()

    with Session(engine) as session:
        _queue(session, monitor)
        result = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=lambda *_: {
                "status": "already_indexed",
                "document_id": "22222222-2222-2222-2222-222222222222",
            },
        )
        record = session.scalar(select(SourceMonitorDiscoveryRecord))

    assert result.duplicate_count == 1
    assert record is not None and record.status == "duplicate"
    assert record.document_id == "22222222-2222-2222-2222-222222222222"


def test_operational_failure_stays_pending_with_symbolic_error() -> None:
    engine = _engine()
    monitor = _monitor()

    def ingest(source_id: str, url: str):
        raise RuntimeError("raw provider details must not be persisted")

    with Session(engine) as session:
        _queue(session, monitor)
        result = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=ingest,
        )
        record = session.scalar(select(SourceMonitorDiscoveryRecord))

    assert result.failed_count == 1
    assert record is not None
    assert record.status == "pending"
    assert record.attempt_count == 1
    assert record.last_error_code == "ingestion_runtime_error"


def test_queued_url_is_revalidated_immediately_before_ingestion() -> None:
    engine = _engine()
    monitor = _monitor()
    calls = 0

    def ingest(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("policy-rejected URL must not be ingested")

    now = datetime(2026, 9, 12, 11, 0, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            SourceMonitorDiscoveryRecord(
                id=str(uuid4()),
                discovery_key="c" * 64,
                item_fingerprint="d" * 64,
                monitor_id=monitor.monitor_id,
                source_id=monitor.source_id,
                url="https://example.com/not-rbi",
                title="Tampered",
                publication_date=None,
                status="pending",
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

        result = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=now + timedelta(minutes=1),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=ingest,
        )
        record = session.scalar(select(SourceMonitorDiscoveryRecord))

    assert calls == 0
    assert result.rejected_count == 1
    assert record is not None and record.status == "rejected"
    assert record.last_error_code == "source_policy_rejection"


def test_processing_is_bounded_by_monitor_limit() -> None:
    engine = _engine()
    monitor = _monitor(max_new_documents_per_run=2)
    calls = 0

    def ingest(source_id: str, url: str):
        nonlocal calls
        calls += 1
        return {"status": "indexed", "document_id": str(uuid4())}

    with Session(engine) as session:
        _queue(session, monitor, count=3)
        result = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=datetime(2026, 9, 12, 11, 0, tzinfo=UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=ingest,
        )
        records = list(session.scalars(select(SourceMonitorDiscoveryRecord)))

    assert calls == 2
    assert result.selected_count == 2
    assert sum(record.status == "pending" for record in records) == 1
    assert sum(record.status == "ingested" for record in records) == 2
