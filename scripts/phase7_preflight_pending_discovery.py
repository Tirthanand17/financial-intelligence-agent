import argparse
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.controlled import snapshot_monitoring_database
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.preflight import preflight_discovered_url
from app.monitoring.registry import get_monitor
from app.storage.database import (
    SourceMonitorDiscoveryRecord,
    find_document_by_sha,
    get_session,
)
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Phase 7 preflight of one persisted pending discovery. "
            "The selected public URL is downloaded and validated in memory only."
        )
    )
    parser.add_argument(
        "--monitor-id",
        default="rbi-press-releases-rss",
        help="Registered monitor ID whose oldest pending item should be preflighted.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for capacity measurements and one public-source download.",
    )
    args = parser.parse_args()

    if not args.allow_network:
        print("BLOCKED: --allow-network is required; no network calls were made.")
        return

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print("BLOCKED: SOURCE_MONITORING_ENABLED must remain false for this read-only preflight.")
        return
    if settings.source_auto_ingest_enabled:
        print("BLOCKED: SOURCE_AUTO_INGEST_ENABLED must remain false.")
        return
    if settings.trust_promotion_enabled:
        print("BLOCKED: TRUST_PROMOTION_ENABLED must remain false.")
        return

    monitor = get_monitor(args.monitor_id)
    s3_client = get_s3_client()
    qdrant_client = get_qdrant_client()

    print("PHASE 7 PENDING DISCOVERY PREFLIGHT - READ ONLY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print("SOURCE_MONITORING_ENABLED: false")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")

    with get_session() as session:
        usage_before = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        services, capacity = assess_measured_capacity(
            usage_before,
            CloudBudgetLimits(
                supabase_max_mb=settings.monitor_supabase_max_mb,
                backblaze_b2_max_mb=settings.monitor_b2_max_mb,
                qdrant_max_points=settings.monitor_qdrant_max_points,
                low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
            ),
        )
        for service in services:
            print(
                f"CAPACITY {service.service}: state={service.state.value} "
                f"detail={service.detail or '-'}"
            )
        if not capacity.allow_ingestion:
            blockers = ",".join(capacity.blocking_services) or "-"
            print(
                "FINAL: BLOCKED - preflight was not attempted because capacity is not safe. "
                f"reason={capacity.reason} blockers={blockers}"
            )
            return

        record = session.scalar(
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
            .limit(1)
        )
        if record is None:
            print("FINAL: BLOCKED - no pending discovery is available for preflight.")
            return

        before_db = snapshot_monitoring_database(session)
        before_record = (
            record.id,
            record.status,
            record.document_id,
            record.seen_count,
            record.attempt_count,
            record.last_attempt_at,
            record.last_error_code,
        )

        print(f"QUEUE ITEM: title={record.title or '-'} publication_date={record.publication_date or '-'}")

        try:
            result = preflight_discovered_url(record.source_id, record.url)
        except ConnectionError:
            print("FINAL: BLOCKED - source download failed with transient_network_error; no writes were made.")
            session.rollback()
            return
        except httpx.HTTPError:
            print("FINAL: BLOCKED - source download failed with http_error; no writes were made.")
            session.rollback()
            return
        except ValueError:
            print("FINAL: BLOCKED - source evidence failed trusted preflight validation; no writes were made.")
            session.rollback()
            return

        existing = find_document_by_sha(session, result.sha256)
        after_db = snapshot_monitoring_database(session)
        refreshed = session.get(SourceMonitorDiscoveryRecord, record.id)
        after_record = None
        if refreshed is not None:
            after_record = (
                refreshed.id,
                refreshed.status,
                refreshed.document_id,
                refreshed.seen_count,
                refreshed.attempt_count,
                refreshed.last_attempt_at,
                refreshed.last_error_code,
            )

        usage_after = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )

        blockers: list[str] = []
        if after_db != before_db:
            blockers.append("database_table_counts_changed")
        if after_record != before_record:
            blockers.append("discovery_record_changed")
        if (
            usage_before.backblaze_b2_bytes is None
            or usage_after.backblaze_b2_bytes is None
            or usage_before.backblaze_b2_bytes != usage_after.backblaze_b2_bytes
        ):
            blockers.append("backblaze_b2_changed_or_unknown")
        if (
            usage_before.qdrant_points is None
            or usage_after.qdrant_points is None
            or usage_before.qdrant_points != usage_after.qdrant_points
        ):
            blockers.append("qdrant_changed_or_unknown")

        print(
            "PREFLIGHT: "
            f"content_type={result.content_type} bytes={result.content_bytes} "
            f"text_chars={result.text_chars} chunks={result.chunk_count} "
            f"eligible_claims={result.eligible_claim_count} "
            f"publication_date={result.publication_date or '-'}"
        )
        print(f"SHA256: {result.sha256}")
        print(f"EXISTING DOCUMENT: {'yes' if existing is not None else 'no'}")
        print(
            "EXTERNAL DELTA: "
            f"backblaze_b2_bytes={None if usage_before.backblaze_b2_bytes is None or usage_after.backblaze_b2_bytes is None else usage_after.backblaze_b2_bytes - usage_before.backblaze_b2_bytes} "
            f"qdrant_points={None if usage_before.qdrant_points is None or usage_after.qdrant_points is None else usage_after.qdrant_points - usage_before.qdrant_points}"
        )

        session.rollback()
        if blockers:
            print(
                "FINAL: FAIL-ROLLED-BACK - read-only boundary validation failed. "
                f"blockers={','.join(blockers)}"
            )
            return

        print(
            "FINAL: PASS-READ-ONLY - one pending discovery was downloaded and validated "
            "in memory. Queue state, documents, claims, trust, Backblaze, and Qdrant were unchanged."
        )


if __name__ == "__main__":
    main()
