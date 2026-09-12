from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.monitoring.capacity import evaluate_capacity
from app.monitoring.models import CapacityState, MonitorDefinition, MonitorRunOutcome, ServiceCapacity
from app.monitoring.runner import probe_monitor_once
from app.storage.database import Base, SourceMonitorRunRecord, SourceMonitorStateRecord


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _monitor(*, enabled: bool = True) -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=enabled,
        max_new_documents_per_run=2,
    )


def _safe_capacity():
    return evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.OK),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )


def _times():
    start = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    return start, start + timedelta(seconds=2)


def test_global_monitoring_gate_defaults_off_and_never_touches_network() -> None:
    engine = _engine()
    start, end = _times()
    calls = 0

    def download(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    with Session(engine) as session:
        result = probe_monitor_once(
            session,
            _monitor(enabled=True),
            _safe_capacity(),
            started_at=start,
            finished_at=end,
            download_feed=download,
        )
        run = session.scalar(select(SourceMonitorRunRecord))

    assert calls == 0
    assert result.outcome is MonitorRunOutcome.DISABLED
    assert result.reason == "source_monitoring_disabled"
    assert run is not None and run.reason == "source_monitoring_disabled"


def test_disabled_monitor_never_touches_network() -> None:
    engine = _engine()
    start, end = _times()
    calls = 0

    def download(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    with Session(engine) as session:
        result = probe_monitor_once(
            session,
            _monitor(enabled=False),
            _safe_capacity(),
            started_at=start,
            finished_at=end,
            source_monitoring_enabled=True,
            download_feed=download,
        )

    assert calls == 0
    assert result.outcome is MonitorRunOutcome.DISABLED
    assert result.reason == "monitor_disabled"


def test_capacity_pause_happens_before_network() -> None:
    engine = _engine()
    start, end = _times()
    capacity = evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.LOW),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )
    calls = 0

    def download(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("network must not be called")

    with Session(engine) as session:
        result = probe_monitor_once(
            session,
            _monitor(),
            capacity,
            started_at=start,
            finished_at=end,
            source_monitoring_enabled=True,
            download_feed=download,
        )

    assert calls == 0
    assert result.outcome is MonitorRunOutcome.PAUSED_CAPACITY
    assert result.blocking_services == ("backblaze_b2",)


def test_probe_discovers_bounded_items_but_does_not_ingest_links() -> None:
    engine = _engine()
    start, end = _times()
    feed = b"""<rss><channel>
      <item><title>One</title><link>https://www.rbi.org.in/1</link></item>
      <item><title>Two</title><link>https://www.rbi.org.in/2</link></item>
      <item><title>Three</title><link>https://www.rbi.org.in/3</link></item>
    </channel></rss>"""

    def download(source_id: str, url: str):
        assert source_id == "rbi"
        assert url == "https://rbi.org.in/pressreleases_rss.xml"
        return SimpleNamespace(content=feed, content_type="application/rss+xml")

    with Session(engine) as session:
        result = probe_monitor_once(
            session,
            _monitor(),
            _safe_capacity(),
            started_at=start,
            finished_at=end,
            source_monitoring_enabled=True,
            download_feed=download,
        )
        run = session.scalar(select(SourceMonitorRunRecord))
        state = session.scalar(select(SourceMonitorStateRecord))

    assert result.outcome is MonitorRunOutcome.SUCCESS
    assert result.discovered_count == 2
    assert result.ingested_count == 0
    assert result.duplicate_count == 0
    assert run is not None and run.discovered_count == 2
    assert run.ingested_count == 0
    assert state is not None and state.state == "ready"


def test_probe_counts_rejected_cross_host_items_without_following_them() -> None:
    engine = _engine()
    start, end = _times()
    feed = b"""<rss><channel>
      <item><title>Unsafe</title><link>https://example.com/1</link></item>
      <item><title>Safe</title><link>https://www.rbi.org.in/2</link></item>
    </channel></rss>"""

    with Session(engine) as session:
        result = probe_monitor_once(
            session,
            _monitor(),
            _safe_capacity(),
            started_at=start,
            finished_at=end,
            source_monitoring_enabled=True,
            download_feed=lambda *_: SimpleNamespace(
                content=feed,
                content_type="application/rss+xml",
            ),
        )

    assert result.outcome is MonitorRunOutcome.SUCCESS
    assert result.discovered_count == 1
    assert result.rejected_discovery_count == 1


def test_network_failure_is_recorded_as_symbolic_error_only() -> None:
    engine = _engine()
    start, end = _times()

    def download(source_id: str, url: str):
        raise ConnectionError("secret-bearing raw transport details should not persist")

    with Session(engine) as session:
        result = probe_monitor_once(
            session,
            _monitor(),
            _safe_capacity(),
            started_at=start,
            finished_at=end,
            source_monitoring_enabled=True,
            download_feed=download,
        )
        run = session.scalar(select(SourceMonitorRunRecord))

    assert result.outcome is MonitorRunOutcome.FAILED
    assert result.error_code == "transient_network_error"
    assert run is not None
    assert run.error_code == "transient_network_error"
    assert run.reason == "source_download_failed"


def test_non_xml_monitor_response_is_rejected() -> None:
    engine = _engine()
    start, end = _times()

    with Session(engine) as session:
        result = probe_monitor_once(
            session,
            _monitor(),
            _safe_capacity(),
            started_at=start,
            finished_at=end,
            source_monitoring_enabled=True,
            download_feed=lambda *_: SimpleNamespace(
                content=b"<html>not a feed</html>",
                content_type="text/html",
            ),
        )

    assert result.outcome is MonitorRunOutcome.FAILED
    assert result.error_code == "unexpected_feed_content_type"
