from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.monitoring.capacity import evaluate_capacity
from app.monitoring.discovery import DiscoveredFeedItem
from app.monitoring.discovery_storage import record_discovered_items
from app.monitoring.models import CapacityState, MonitorDefinition, ServiceCapacity
from app.monitoring.processor import (
    process_pending_discoveries,
    process_specific_pending_discovery,
)
from app.monitoring.queue_retry import assess_discovery_retry, next_discovery_retry_at
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


def test_fresh_discovery_is_immediately_ready() -> None:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    decision = assess_discovery_retry(
        now=now,
        interval_minutes=60,
        attempt_count=0,
        last_attempt_at=None,
        last_error_code=None,
    )

    assert decision.due is True
    assert decision.reason == "discovery_ready"
    assert decision.next_eligible_at is None


def test_failed_discovery_uses_exponential_backoff_capped_at_24_hours() -> None:
    last_attempt = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)

    first_retry = next_discovery_retry_at(
        interval_minutes=60,
        attempt_count=1,
        last_attempt_at=last_attempt,
        last_error_code="http_error",
    )
    capped_retry = next_discovery_retry_at(
        interval_minutes=60,
        attempt_count=20,
        last_attempt_at=last_attempt,
        last_error_code="http_error",
    )

    assert first_retry == last_attempt + timedelta(hours=2)
    assert capped_retry == last_attempt + timedelta(hours=24)


def test_incomplete_failure_metadata_fails_closed() -> None:
    decision = assess_discovery_retry(
        now=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        interval_minutes=60,
        attempt_count=1,
        last_attempt_at=None,
        last_error_code="http_error",
    )

    assert decision.due is False
    assert decision.reason == "retry_metadata_incomplete"
    assert decision.next_eligible_at is None


def test_specific_processing_refuses_failed_row_before_retry_time() -> None:
    engine = _engine()
    monitor = _monitor()
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    calls = 0

    def ingest(*_):
        nonlocal calls
        calls += 1
        raise AssertionError("backed-off row must not be ingested")

    with Session(engine) as session:
        _queue(session, monitor)
        record = session.scalar(select(SourceMonitorDiscoveryRecord))
        assert record is not None
        record.attempt_count = 1
        record.last_attempt_at = now
        record.last_error_code = "ingestion_runtime_error"
        session.commit()

        result = process_specific_pending_discovery(
            session,
            monitor,
            _safe_capacity(),
            record_id=record.id,
            now=now + timedelta(minutes=30),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=ingest,
        )
        refreshed = session.get(SourceMonitorDiscoveryRecord, record.id)

    assert calls == 0
    assert result.reason == "retry_backoff"
    assert result.selected_count == 0
    assert refreshed is not None
    assert refreshed.status == "pending"
    assert refreshed.attempt_count == 1


def test_batch_skips_backed_off_failure_and_processes_fresh_row() -> None:
    engine = _engine()
    monitor = _monitor()
    now = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    seen_urls: list[str] = []

    def ingest(_source_id: str, url: str):
        seen_urls.append(url)
        return {"status": "indexed", "document_id": str(uuid4())}

    with Session(engine) as session:
        _queue(session, monitor, count=2)
        records = list(
            session.scalars(
                select(SourceMonitorDiscoveryRecord).order_by(
                    SourceMonitorDiscoveryRecord.first_seen_at,
                    SourceMonitorDiscoveryRecord.id,
                )
            )
        )
        assert len(records) == 2
        failed = records[0]
        fresh = records[1]
        failed.attempt_count = 1
        failed.last_attempt_at = now
        failed.last_error_code = "http_error"
        session.commit()

        result = process_pending_discoveries(
            session,
            monitor,
            _safe_capacity(),
            now=now + timedelta(minutes=30),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            limit=1,
            ingest=ingest,
        )
        failed_after = session.get(SourceMonitorDiscoveryRecord, failed.id)
        fresh_after = session.get(SourceMonitorDiscoveryRecord, fresh.id)

    assert result.selected_count == 1
    assert result.ingested_count == 1
    assert seen_urls == [fresh.url]
    assert failed_after is not None and failed_after.status == "pending"
    assert failed_after.attempt_count == 1
    assert fresh_after is not None and fresh_after.status == "ingested"


def test_due_failed_row_can_be_retried_after_backoff() -> None:
    engine = _engine()
    monitor = _monitor()
    last_attempt = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    with Session(engine) as session:
        _queue(session, monitor)
        record = session.scalar(select(SourceMonitorDiscoveryRecord))
        assert record is not None
        record.attempt_count = 1
        record.last_attempt_at = last_attempt
        record.last_error_code = "transient_network_error"
        session.commit()

        result = process_specific_pending_discovery(
            session,
            monitor,
            _safe_capacity(),
            record_id=record.id,
            now=last_attempt + timedelta(hours=2),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            ingest=lambda *_: {"status": "indexed", "document_id": str(uuid4())},
        )
        refreshed = session.get(SourceMonitorDiscoveryRecord, record.id)

    assert result.ingested_count == 1
    assert refreshed is not None and refreshed.status == "ingested"
    assert refreshed.last_error_code is None
    assert refreshed.attempt_count == 2
