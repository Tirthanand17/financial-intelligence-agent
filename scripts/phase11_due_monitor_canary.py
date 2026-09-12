import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.ingestion.downloader import download_trusted_document
from app.monitoring.controlled import snapshot_monitoring_database
from app.monitoring.gate_canary import assess_monitoring_gate_canary
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.registry import get_monitor
from app.monitoring.runner import probe_monitor_once
from app.monitoring.scheduled_gate import assess_scheduled_monitor_gate
from app.storage.database import SourceMonitorStateRecord, get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def _delta(old: int | None, new: int | None) -> int | None:
    if old is None or new is None:
        return None
    return new - old


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 11 cadence-aware recurring monitor canary. It first evaluates "
            "persisted cadence/backoff state. If the monitor is not due it exits "
            "without source/network work or writes. If due, it may run exactly one "
            "bounded discovery-only monitor cycle with the Phase 10 safety boundary."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required before a due invocation may measure clouds or fetch the feed.",
    )
    parser.add_argument(
        "--allow-monitor-write",
        action="store_true",
        help="Required before a due invocation may commit monitor/discovery metadata.",
    )
    args = parser.parse_args()

    settings = get_settings()
    monitor = get_monitor(args.monitor_id)

    print("PHASE 11 CADENCE-AWARE MONITOR CANARY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print(f"CONFIGURED INTERVAL MINUTES: {monitor.interval_minutes}")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    with get_session() as session:
        state = session.scalar(
            select(SourceMonitorStateRecord).where(
                SourceMonitorStateRecord.monitor_id == monitor.monitor_id
            )
        )
        now = datetime.now(UTC)
        last_checked_at = state.last_checked_at if state is not None else None
        consecutive_failures = state.consecutive_failures if state is not None else 0
        schedule = assess_scheduled_monitor_gate(
            monitor,
            now=now,
            last_checked_at=last_checked_at,
            consecutive_failures=consecutive_failures,
        )

        print(f"LAST CHECKED AT: {last_checked_at.isoformat() if last_checked_at else '-'}")
        print(f"CONSECUTIVE FAILURES: {consecutive_failures}")
        print(f"NOW: {now.isoformat()}")
        print(
            "NEXT ELIGIBLE CHECK: "
            f"{schedule.next_eligible_at.isoformat() if schedule.next_eligible_at else '-'}"
        )
        print(f"DUE NOW: {str(schedule.due).lower()} reason={schedule.reason}")

        if not schedule.due:
            print(
                "FINAL: PASS-NOT-DUE - cadence/backoff guard prevented the monitor "
                "from fetching the RBI feed or writing database/B2/Qdrant state."
            )
            return

        if not args.allow_network or not args.allow_monitor_write:
            print(
                "FINAL: BLOCKED-DUE - monitor is due, but both --allow-network and "
                "--allow-monitor-write are required for this controlled canary."
            )
            return

        if not settings.source_monitoring_enabled:
            print("FINAL: BLOCKED-DUE - SOURCE_MONITORING_ENABLED must be true.")
            return
        if settings.source_auto_ingest_enabled:
            print("FINAL: BLOCKED-DUE - SOURCE_AUTO_INGEST_ENABLED must remain false.")
            return
        if settings.trust_promotion_enabled:
            print("FINAL: BLOCKED-DUE - TRUST_PROMOTION_ENABLED must remain false.")
            return

        s3_client = get_s3_client()
        qdrant_client = get_qdrant_client()
        limits = CloudBudgetLimits(
            supabase_max_mb=settings.monitor_supabase_max_mb,
            backblaze_b2_max_mb=settings.monitor_b2_max_mb,
            qdrant_max_points=settings.monitor_qdrant_max_points,
            low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
        )
        usage_before = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        services, capacity = assess_measured_capacity(usage_before, limits)
        for service in services:
            print(
                f"CAPACITY {service.service}: state={service.state.value} "
                f"detail={service.detail or '-'}"
            )
        if not capacity.allow_ingestion:
            blockers = ",".join(capacity.blocking_services) or "-"
            print(
                "FINAL: BLOCKED-DUE - cloud capacity is not safe. "
                f"reason={capacity.reason} blockers={blockers}"
            )
            return

        before = snapshot_monitoring_database(session)
        started_at = datetime.now(UTC)
        try:
            downloaded = download_trusted_document(monitor.source_id, monitor.url)
        except ConnectionError:
            session.rollback()
            print(
                "FINAL: BLOCKED-DUE - feed download failed with "
                "transient_network_error; no writes committed."
            )
            return
        except httpx.HTTPError:
            session.rollback()
            print("FINAL: BLOCKED-DUE - feed download failed with http_error; no writes committed.")
            return
        except ValueError:
            session.rollback()
            print(
                "FINAL: BLOCKED-DUE - feed failed source-policy validation; "
                "no writes committed."
            )
            return

        finished_at = datetime.now(UTC)
        result = probe_monitor_once(
            session,
            monitor,
            capacity,
            started_at=started_at,
            finished_at=finished_at,
            source_monitoring_enabled=settings.source_monitoring_enabled,
            download_feed=lambda *_: downloaded,
            commit=False,
        )
        staged = snapshot_monitoring_database(session)
        usage_after = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        b2_delta = _delta(usage_before.backblaze_b2_bytes, usage_after.backblaze_b2_bytes)
        qdrant_delta = _delta(usage_before.qdrant_points, usage_after.qdrant_points)
        canary = assess_monitoring_gate_canary(
            before,
            staged,
            result,
            source_monitoring_enabled=settings.source_monitoring_enabled,
            source_auto_ingest_enabled=settings.source_auto_ingest_enabled,
            trust_promotion_enabled=settings.trust_promotion_enabled,
            max_new_documents_per_run=monitor.max_new_documents_per_run,
            backblaze_b2_delta=b2_delta,
            qdrant_points_delta=qdrant_delta,
        )

        print(
            f"RUN: outcome={result.outcome.value} reason={result.reason} "
            f"discovered={result.discovered_count} rejected={result.rejected_discovery_count} "
            f"ingested={result.ingested_count} duplicate={result.duplicate_count}"
        )
        print(
            "STAGED DATABASE DELTA: "
            f"documents={staged.documents - before.documents} "
            f"claims={staged.claims - before.claims} "
            f"verification_events={staged.claim_verification_events - before.claim_verification_events} "
            f"trust_events={staged.claim_trust_events - before.claim_trust_events} "
            f"discoveries={staged.monitor_discoveries - before.monitor_discoveries} "
            f"monitor_runs={staged.monitor_runs - before.monitor_runs} "
            f"monitor_states={staged.monitor_states - before.monitor_states}"
        )
        print(
            "EXTERNAL DELTA: "
            f"backblaze_b2_bytes={b2_delta} qdrant_points={qdrant_delta}"
        )

        if not canary.passed:
            session.rollback()
            print(
                "FINAL: FAIL-ROLLED-BACK - due monitor run did not reconcile; "
                "staged metadata was not committed. "
                f"blockers={','.join(canary.blockers) or '-'}"
            )
            return

        session.commit()
        print(
            "FINAL: PASS-DUE-COMMITTED - exactly one cadence-eligible discovery-only "
            "monitor run completed and reconciled. Automatic ingestion and trust "
            "promotion remained disabled."
        )


if __name__ == "__main__":
    main()
