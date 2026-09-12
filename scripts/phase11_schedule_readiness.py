import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.registry import get_monitor
from app.monitoring.schedule import is_monitor_due, next_check_at
from app.storage.database import SourceMonitorStateRecord, get_session


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only Phase 11 check of the persisted monitor cadence/backoff state."
    )
    parser.add_argument(
        "--monitor-id",
        default="rbi-press-releases-rss",
        help="Registered monitor ID to inspect.",
    )
    args = parser.parse_args()

    settings = get_settings()
    monitor = get_monitor(args.monitor_id)
    now = datetime.now(UTC)

    print("PHASE 11 RECURRING MONITOR SCHEDULE READINESS - READ ONLY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print(f"CONFIGURED INTERVAL MINUTES: {monitor.interval_minutes}")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    if settings.source_auto_ingest_enabled:
        print("FINAL: BLOCKED - SOURCE_AUTO_INGEST_ENABLED must remain false for this Phase 11 readiness check.")
        return
    if settings.trust_promotion_enabled:
        print("FINAL: BLOCKED - TRUST_PROMOTION_ENABLED must remain false for this Phase 11 readiness check.")
        return

    with get_session() as session:
        state = session.scalar(
            select(SourceMonitorStateRecord).where(
                SourceMonitorStateRecord.monitor_id == monitor.monitor_id
            )
        )

        if state is None:
            print("FINAL: BLOCKED - no persisted monitor state exists yet.")
            return

        due_at = next_check_at(
            monitor,
            last_checked_at=state.last_checked_at,
            consecutive_failures=state.consecutive_failures,
        )
        due = is_monitor_due(
            monitor,
            now=now,
            last_checked_at=state.last_checked_at,
            consecutive_failures=state.consecutive_failures,
        )

        print(f"STATE: {state.state}")
        print(f"REASON: {state.reason}")
        print(f"CONSECUTIVE FAILURES: {state.consecutive_failures}")
        print(
            "LAST CHECKED AT: "
            + (state.last_checked_at.isoformat() if state.last_checked_at else "-")
        )
        print("NOW: " + now.isoformat())
        print("NEXT ELIGIBLE CHECK: " + (due_at.isoformat() if due_at else "immediately"))
        print(f"DUE NOW: {str(due).lower()}")

    print(
        "FINAL: PASS-READ-ONLY - persisted cadence/backoff state was evaluated without "
        "fetching the source feed or changing database, Backblaze B2, or Qdrant state."
    )


if __name__ == "__main__":
    main()
