from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.monitoring.capacity import evaluate_capacity
from app.monitoring.models import CapacityState, MonitorDefinition, ServiceCapacity
from app.monitoring.runner import probe_monitor_once
from app.storage.database import (
    Base,
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
)


def _safe_capacity():
    return evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.OK),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )


def _monitor() -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=2,
    )


def test_commit_false_stages_run_and_discoveries_then_allows_rollback() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    start = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    end = start + timedelta(seconds=1)
    feed = b"""<rss><channel>
      <item><title>One</title><link>https://www.rbi.org.in/1</link></item>
      <item><title>Two</title><link>https://www.rbi.org.in/2</link></item>
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
            commit=False,
        )

        assert result.discovered_count == 2
        assert session.scalar(select(func.count()).select_from(SourceMonitorRunRecord)) == 1
        assert session.scalar(select(func.count()).select_from(SourceMonitorDiscoveryRecord)) == 2
        session.rollback()

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SourceMonitorRunRecord)) == 0
        assert session.scalar(select(func.count()).select_from(SourceMonitorDiscoveryRecord)) == 0
