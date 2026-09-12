import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.processor import _select_eligible_pending_records
from app.monitoring.queue_retry import assess_discovery_retry
from app.monitoring.registry import get_monitor
from app.storage.database import SourceMonitorDiscoveryRecord, get_session


def _snapshot_rows(session, *, monitor_id: str, source_id: str):
    rows = list(
        session.scalars(
            select(SourceMonitorDiscoveryRecord)
            .where(
                SourceMonitorDiscoveryRecord.monitor_id == monitor_id,
                SourceMonitorDiscoveryRecord.source_id == source_id,
            )
            .order_by(SourceMonitorDiscoveryRecord.id)
        )
    )
    return {
        row.id: (
            row.status,
            row.document_id,
            row.seen_count,
            row.attempt_count,
            row.last_attempt_at,
            row.last_error_code,
        )
        for row in rows
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 13 transactional replay of queue retry selection. One real pending "
            "row is staged as a recent failure, the production selector is evaluated, "
            "and the transaction is always rolled back. No network/B2/Qdrant work occurs."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    parser.add_argument("--allow-transactional-replay", action="store_true")
    args = parser.parse_args()

    if not args.allow_transactional_replay:
        print("BLOCKED: --allow-transactional-replay is required. No changes were staged.")
        return

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print("BLOCKED: SOURCE_MONITORING_ENABLED must remain false.")
        return
    if settings.source_auto_ingest_enabled:
        print("BLOCKED: SOURCE_AUTO_INGEST_ENABLED must remain false.")
        return
    if settings.trust_promotion_enabled:
        print("BLOCKED: TRUST_PROMOTION_ENABLED must remain false.")
        return

    monitor = get_monitor(args.monitor_id)
    now = datetime.now(UTC)

    print("PHASE 13 RETRY SELECTOR REPLAY - ALWAYS ROLLED BACK")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print(f"RETRY BASE INTERVAL MINUTES: {monitor.interval_minutes}")
    print("SOURCE_MONITORING_ENABLED: false")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")

    with get_session() as session:
        before = _snapshot_rows(
            session,
            monitor_id=monitor.monitor_id,
            source_id=monitor.source_id,
        )
        pending = list(
            session.scalars(
                select(SourceMonitorDiscoveryRecord)
                .where(
                    SourceMonitorDiscoveryRecord.monitor_id == monitor.monitor_id,
                    SourceMonitorDiscoveryRecord.source_id == monitor.source_id,
                    SourceMonitorDiscoveryRecord.status == "pending",
                    SourceMonitorDiscoveryRecord.last_error_code.is_(None),
                )
                .order_by(
                    SourceMonitorDiscoveryRecord.first_seen_at,
                    SourceMonitorDiscoveryRecord.id,
                )
            )
        )

        if len(pending) < 2:
            session.rollback()
            print(
                "FINAL: BLOCKED - at least two fresh pending rows are required to prove "
                "that a backed-off failure cannot starve fresh work. No changes committed."
            )
            return

        staged_failed = pending[0]
        staged_failed_id = staged_failed.id
        staged_failed_title = staged_failed.title or "-"
        staged_failed.attempt_count = 1
        staged_failed.last_attempt_at = now
        staged_failed.last_error_code = "transient_network_error"
        session.flush()

        during_backoff = now + timedelta(minutes=30)
        retry_now = assess_discovery_retry(
            now=during_backoff,
            interval_minutes=monitor.interval_minutes,
            attempt_count=staged_failed.attempt_count,
            last_attempt_at=staged_failed.last_attempt_at,
            last_error_code=staged_failed.last_error_code,
        )
        selected = _select_eligible_pending_records(
            session,
            monitor,
            now=during_backoff,
            limit=1,
        )
        selected_id = selected[0].id if selected else None
        selected_title = selected[0].title or "-" if selected else "none"
        failed_was_selected = selected_id == staged_failed_id

        at_retry_time = now + timedelta(hours=2)
        retry_due = assess_discovery_retry(
            now=at_retry_time,
            interval_minutes=monitor.interval_minutes,
            attempt_count=staged_failed.attempt_count,
            last_attempt_at=staged_failed.last_attempt_at,
            last_error_code=staged_failed.last_error_code,
        )

        blockers: list[str] = []
        if retry_now.due or retry_now.reason != "retry_backoff":
            blockers.append("retry:recent_failure_not_deferred")
        if retry_now.next_eligible_at != at_retry_time:
            blockers.append("retry:first_backoff_not_two_hours")
        if not selected:
            blockers.append("selector:no_fresh_row_selected")
        if failed_was_selected:
            blockers.append("selector:backed_off_failure_selected")
        if not retry_due.due or retry_due.reason != "retry_due":
            blockers.append("retry:failed_row_not_due_after_backoff")

        print(
            "STAGED FAILURE: "
            f"title={staged_failed_title} attempt_count=1 error_code=transient_network_error"
        )
        print(
            "BACKOFF CHECK +30M: "
            f"due={str(retry_now.due).lower()} reason={retry_now.reason} "
            f"next_eligible={retry_now.next_eligible_at.isoformat() if retry_now.next_eligible_at else '-'}"
        )
        print(
            "SELECTOR DURING BACKOFF: "
            f"selected_title={selected_title} backed_off_item_selected={str(failed_was_selected).lower()}"
        )
        print(
            "RETRY CHECK +2H: "
            f"due={str(retry_due.due).lower()} reason={retry_due.reason}"
        )

        session.rollback()

    with get_session() as verification_session:
        after = _snapshot_rows(
            verification_session,
            monitor_id=monitor.monitor_id,
            source_id=monitor.source_id,
        )
        verification_session.rollback()

    restored = before == after
    print(f"ROLLBACK VERIFIED: {str(restored).lower()}")
    if not restored:
        blockers.append("database:queue_state_not_restored")

    if blockers:
        print(
            "FINAL: FAIL-ROLLED-BACK - retry selector replay did not satisfy the safety "
            f"contract. blockers={','.join(dict.fromkeys(blockers))}"
        )
        return

    print(
        "FINAL: PASS-ROLLED-BACK - a real pending row was staged as a recent failure, "
        "the production selector skipped it in favor of fresh work, the retry became "
        "eligible after the expected backoff, and all queue state was restored."
    )


if __name__ == "__main__":
    main()
