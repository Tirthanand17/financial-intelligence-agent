import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.probe import probe_feed_read_only
from app.monitoring.registry import get_monitor
from app.storage.database import get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


_MIB = 1024 * 1024


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"{value} bytes ({value / _MIB:.2f} MiB)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Explicit read-only Phase 6 validation. It measures configured cloud "
            "storage usage and probes one registered source feed without writes."
        )
    )
    parser.add_argument(
        "--monitor-id",
        default="rbi-press-releases-rss",
        help="Registered monitor ID to probe.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for this one read-only network validation run.",
    )
    args = parser.parse_args()

    if not args.allow_network:
        print("BLOCKED: no network calls were made.")
        print("Re-run with --allow-network for one explicit read-only validation.")
        return

    settings = get_settings()
    monitor = get_monitor(args.monitor_id)

    with get_session() as session:
        usage = measure_cloud_usage(
            session,
            s3_client=get_s3_client(),
            qdrant_client=get_qdrant_client(),
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )

    services, capacity = assess_measured_capacity(
        usage,
        CloudBudgetLimits(
            supabase_max_mb=settings.monitor_supabase_max_mb,
            backblaze_b2_max_mb=settings.monitor_b2_max_mb,
            qdrant_max_points=settings.monitor_qdrant_max_points,
            low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
        ),
    )
    probe = probe_feed_read_only(monitor)

    print("PHASE 6 CONTROLLED VALIDATION - READ ONLY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")
    print(f"SUPABASE DATABASE: {_format_bytes(usage.supabase_bytes)}")
    print(f"BACKBLAZE B2 OBJECTS: {_format_bytes(usage.backblaze_b2_bytes)}")
    print(f"QDRANT POINTS: {'unknown' if usage.qdrant_points is None else usage.qdrant_points}")
    for service in services:
        print(
            f"CAPACITY {service.service}: state={service.state.value} "
            f"detail={service.detail or '-'}"
        )
    blockers = ",".join(capacity.blocking_services) or "-"
    print(
        f"AUTOMATIC WORK CAPACITY: allowed={str(capacity.allow_ingestion).lower()} "
        f"reason={capacity.reason} blockers={blockers}"
    )
    print(
        f"FEED PROBE: status={probe.status} reason={probe.reason} "
        f"discovered={probe.discovered_count} rejected={probe.rejected_count}"
    )
    print(f"FEED SHA256: {probe.content_sha256 or '-'}")
    print(
        "LATEST FEED PUBLICATION DATE: "
        f"{probe.latest_publication_date.isoformat() if probe.latest_publication_date else '-'}"
    )
    print(
        "FINAL: READ-ONLY - no monitor queue, document, claim, trust, or cloud object state was changed."
    )


if __name__ == "__main__":
    main()
