import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.queue_retry import assess_discovery_retry
from app.monitoring.registry import get_monitor
from app.storage.database import SourceMonitorDiscoveryRecord, get_session


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 13 read-only readiness check for per-item queue retry backoff. "
            "It reads pending discovery metadata only and performs no source, B2, "
            "Qdrant, or database writes."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    args = parser.parse_args()

    settings = get_settings()
    monitor = get_monitor(args.monitor_id)
    now = datetime.now(UTC)

    print("PHASE 13 QUEUE RETRY/BACKOFF READINESS - READ ONLY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print(f"RETRY BASE INTERVAL MINUTES: {monitor.interval_minutes}")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")
    print(f"NOW: {now.isoformat()}")

    with get_session() as session:
        records = list(
            session.scalars(
                select(SourceMonitorDiscoveryRecord)
                .where(
                    SourceMonitorDiscoveryRecord.monitor_id == monitor.monitor_id,
                    SourceMonitorDiscoveryRecord.source_id == monitor.source_id,
                    SourceMonitorDiscoveryRecord.status == "pending",
                )
                .order_by(
                    SourceMonitorDiscoveryRecord.first_seen_at,
                    SourceMonitorDiscoveryRecord.id,
                )
            )
        )

        fresh = []
        retry_due = []
        retry_deferred = []
        retry_metadata_blocked = []
        next_retry_times = []

        for record in records:
            decision = assess_discovery_retry(
                now=now,
                interval_minutes=monitor.interval_minutes,
                attempt_count=record.attempt_count,
                last_attempt_at=record.last_attempt_at,
                last_error_code=record.last_error_code,
            )
            if decision.reason == "discovery_ready":
                fresh.append(record)
            elif decision.reason == "retry_due":
                retry_due.append(record)
            elif decision.reason == "retry_backoff":
                retry_deferred.append(record)
                if decision.next_eligible_at is not None:
                    next_retry_times.append(decision.next_eligible_at)
            else:
                retry_metadata_blocked.append(record)

        next_retry = min(next_retry_times) if next_retry_times else None
        selectable = fresh[0] if fresh else (retry_due[0] if retry_due else None)

        print(f"PENDING TOTAL: {len(records)}")
        print(f"FRESH ELIGIBLE NOW: {len(fresh)}")
        print(f"RETRY ELIGIBLE NOW: {len(retry_due)}")
        print(f"RETRY DEFERRED BY BACKOFF: {len(retry_deferred)}")
        print(f"RETRY BLOCKED - INCOMPLETE METADATA: {len(retry_metadata_blocked)}")
        print(f"NEXT DEFERRED RETRY: {next_retry.isoformat() if next_retry else '-'}")
        if selectable is None:
            print("NEXT SELECTABLE ITEM: none")
        else:
            print(
                "NEXT SELECTABLE ITEM: "
                f"title={selectable.title or '-'} attempt_count={selectable.attempt_count} "
                f"error_code={selectable.last_error_code or '-'}"
            )

        session.rollback()

    print(
        "FINAL: PASS-READ-ONLY - pending queue retry eligibility was evaluated "
        "without fetching any source or changing PostgreSQL, Backblaze B2, or Qdrant."
    )


if __name__ == "__main__":
    main()
