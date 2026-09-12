import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.cycle_plan import PendingRetryState, plan_recurring_cycle
from app.monitoring.registry import get_monitor
from app.storage.database import (
    SourceMonitorDiscoveryRecord,
    SourceMonitorStateRecord,
    get_session,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 14 read-only readiness check for one integrated recurring cycle. "
            "It evaluates monitor cadence plus bounded queue eligibility without "
            "network access or any database/B2/Qdrant write."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    parser.add_argument("--processing-limit", type=int, default=1)
    args = parser.parse_args()

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print("BLOCKED: SOURCE_MONITORING_ENABLED must remain false for readiness.")
        return
    if settings.source_auto_ingest_enabled:
        print("BLOCKED: SOURCE_AUTO_INGEST_ENABLED must remain false for readiness.")
        return
    if settings.trust_promotion_enabled:
        print("BLOCKED: TRUST_PROMOTION_ENABLED must remain false.")
        return

    monitor = get_monitor(args.monitor_id)
    now = datetime.now(UTC)

    print("PHASE 14 INTEGRATED RECURRING CYCLE READINESS - READ ONLY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print(f"CONFIGURED INTERVAL MINUTES: {monitor.interval_minutes}")
    print(f"PROCESSING LIMIT: {args.processing_limit}")
    print("SOURCE_MONITORING_ENABLED: false")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")
    print(f"NOW: {now.isoformat()}")

    with get_session() as session:
        state = session.get(SourceMonitorStateRecord, monitor.monitor_id)
        last_checked_at = state.last_checked_at if state is not None else None
        consecutive_failures = state.consecutive_failures if state is not None else 0

        pending = list(
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
        pending_states = tuple(
            PendingRetryState(
                attempt_count=row.attempt_count,
                last_attempt_at=row.last_attempt_at,
                last_error_code=row.last_error_code,
            )
            for row in pending
        )

        try:
            plan = plan_recurring_cycle(
                monitor,
                now=now,
                last_checked_at=last_checked_at,
                consecutive_failures=consecutive_failures,
                pending_states=pending_states,
                processing_limit=args.processing_limit,
            )
        except ValueError as exc:
            session.rollback()
            print(f"FINAL: BLOCKED - invalid readiness configuration: {exc}")
            return

        print(f"LAST CHECKED AT: {last_checked_at.isoformat() if last_checked_at else '-'}")
        print(f"CONSECUTIVE MONITOR FAILURES: {consecutive_failures}")
        print(
            "MONITOR GATE: "
            f"due={str(plan.monitor_due).lower()} reason={plan.monitor_reason} "
            f"next_eligible={plan.next_monitor_at.isoformat() if plan.next_monitor_at else '-'}"
        )
        print(f"PENDING TOTAL: {len(pending)}")
        print(f"FRESH ELIGIBLE: {plan.fresh_eligible_count}")
        print(f"RETRY ELIGIBLE: {plan.retry_eligible_count}")
        print(f"RETRY DEFERRED: {plan.retry_deferred_count}")
        print(f"RETRY BLOCKED: {plan.retry_blocked_count}")
        print(f"ELIGIBLE PENDING TOTAL: {plan.eligible_pending_count}")
        print(f"PLANNED PROCESSING THIS CYCLE: {plan.planned_processing_count}")
        session.rollback()

    print(
        "FINAL: PASS-READ-ONLY - cadence and queue retry state were combined into "
        "one bounded recurring-cycle plan without source, PostgreSQL, Backblaze B2, "
        "or Qdrant writes."
    )


if __name__ == "__main__":
    main()
