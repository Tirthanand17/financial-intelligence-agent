import argparse
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.batch_readiness import (
    BatchPreflightObservation,
    assess_batch_preflight,
)
from app.monitoring.controlled import snapshot_monitoring_database
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.preflight import preflight_discovered_url
from app.monitoring.registry import get_monitor
from app.storage.database import SourceMonitorDiscoveryRecord, get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def _delta(before: int | None, after: int | None) -> int | None:
    if before is None or after is None:
        return None
    return after - before


def _queue_state(record: SourceMonitorDiscoveryRecord) -> tuple[object, ...]:
    return (
        record.id,
        record.status,
        record.document_id,
        record.seen_count,
        record.attempt_count,
        record.last_error_code,
    )


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, ConnectionError):
        return "transient_network_error"
    if isinstance(exc, httpx.HTTPError):
        return "http_error"
    if isinstance(exc, ValueError):
        return "preflight_validation_error"
    if isinstance(exc, RuntimeError):
        return "preflight_runtime_error"
    return "unexpected_preflight_error"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Phase 8 canary: preflight a small batch of pending source "
            "discoveries without changing queue, document, claim, object, vector, "
            "monitoring, or trust state."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Number of pending items to validate; Phase 8 hard maximum is 3.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for capacity checks and public-source downloads.",
    )
    args = parser.parse_args()

    if not args.allow_network:
        print("BLOCKED: --allow-network is required; no network calls were made.")
        return
    if args.limit < 1 or args.limit > 3:
        print("BLOCKED: --limit must be between 1 and 3 for the Phase 8 canary.")
        return

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print("BLOCKED: SOURCE_MONITORING_ENABLED must remain false during this canary.")
        return
    if settings.source_auto_ingest_enabled:
        print("BLOCKED: SOURCE_AUTO_INGEST_ENABLED must remain false during this canary.")
        return
    if settings.trust_promotion_enabled:
        print("BLOCKED: TRUST_PROMOTION_ENABLED must remain false during this canary.")
        return

    monitor = get_monitor(args.monitor_id)
    s3_client = get_s3_client()
    qdrant_client = get_qdrant_client()
    limits = CloudBudgetLimits(
        supabase_max_mb=settings.monitor_supabase_max_mb,
        backblaze_b2_max_mb=settings.monitor_b2_max_mb,
        qdrant_max_points=settings.monitor_qdrant_max_points,
        low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
    )

    print("PHASE 8 BOUNDED BATCH PREFLIGHT - READ ONLY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print("SOURCE_MONITORING_ENABLED: false")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")
    print(f"CANARY LIMIT: {args.limit}")

    with get_session() as session:
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
                "FINAL: BLOCKED-READ-ONLY - cloud capacity is not safe. "
                f"reason={capacity.reason} blockers={blockers}"
            )
            return

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
                .limit(args.limit)
            )
        )
        if not records:
            print("FINAL: BLOCKED-READ-ONLY - no pending discoveries are available.")
            return

        before_db = snapshot_monitoring_database(session)
        queue_before = {record.id: _queue_state(record) for record in records}
        observations: list[BatchPreflightObservation] = []

        for index, record in enumerate(records, start=1):
            try:
                preflight = preflight_discovered_url(
                    record.source_id,
                    record.url,
                    chunk_size=settings.chunk_size_chars,
                    chunk_overlap=settings.chunk_overlap_chars,
                )
            except Exception as exc:  # secret-safe symbolic reporting only
                error_code = _safe_error_code(exc)
                observations.append(
                    BatchPreflightObservation(
                        record_id=record.id,
                        passed=False,
                        error_code=error_code,
                    )
                )
                print(
                    f"ITEM {index}: status=failed error_code={error_code} "
                    f"title={record.title or '-'}"
                )
                continue

            observations.append(
                BatchPreflightObservation(
                    record_id=record.id,
                    passed=True,
                    content_bytes=preflight.content_bytes,
                    chunk_count=preflight.chunk_count,
                    eligible_claim_count=preflight.eligible_claim_count,
                    publication_date=preflight.publication_date,
                )
            )
            print(
                f"ITEM {index}: status=pass title={record.title or '-'} "
                f"publication_date={preflight.publication_date or '-'} "
                f"bytes={preflight.content_bytes} chunks={preflight.chunk_count} "
                f"eligible_claims={preflight.eligible_claim_count}"
            )
            del preflight

        # The preflight path is read-only. Roll back defensively anyway before
        # taking the after-snapshots so accidental ORM mutations cannot commit.
        session.rollback()
        after_db = snapshot_monitoring_database(session)
        refreshed = {
            row.id: _queue_state(row)
            for row in session.scalars(
                select(SourceMonitorDiscoveryRecord).where(
                    SourceMonitorDiscoveryRecord.id.in_(tuple(queue_before))
                )
            )
        }
        usage_after = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )

        decision = assess_batch_preflight(
            tuple(observations),
            requested_limit=args.limit,
        )
        blockers = list(decision.blockers)
        if before_db != after_db:
            blockers.append("database:table_counts_changed")
        if refreshed != queue_before:
            blockers.append("queue:selected_rows_changed")

        b2_delta = _delta(usage_before.backblaze_b2_bytes, usage_after.backblaze_b2_bytes)
        qdrant_delta = _delta(usage_before.qdrant_points, usage_after.qdrant_points)
        if b2_delta != 0:
            blockers.append("external:backblaze_changed")
        if qdrant_delta != 0:
            blockers.append("external:qdrant_changed")

        print(
            "BATCH RESULT: "
            f"selected={decision.selected_count} passed={decision.passed_count} "
            f"failed={decision.failed_count} total_bytes={decision.total_content_bytes}"
        )
        print(
            "EXTERNAL DELTA: "
            f"backblaze_b2_bytes={b2_delta} qdrant_points={qdrant_delta}"
        )

        blockers = list(dict.fromkeys(blockers))
        if blockers:
            print(
                "FINAL: BLOCKED-READ-ONLY - bounded batch readiness did not pass; "
                "no queue/document/claim/trust/object/vector writes were committed. "
                f"blockers={','.join(blockers)}"
            )
            return

        print(
            "FINAL: PASS-READ-ONLY - bounded pending-item sample passed trusted "
            "preflight with queue/database/B2/Qdrant state unchanged. Automatic "
            "monitoring and ingestion remain disabled."
        )


if __name__ == "__main__":
    main()
