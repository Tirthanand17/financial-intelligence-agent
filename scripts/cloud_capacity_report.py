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
from app.storage.database import get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


_MIB = 1024 * 1024


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"{value} bytes ({value / _MIB:.2f} MiB)"


def _format_value(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def main() -> None:
    settings = get_settings()

    with get_session() as session:
        usage = measure_cloud_usage(
            session,
            s3_client=get_s3_client(),
            qdrant_client=get_qdrant_client(),
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )

    services, decision = assess_measured_capacity(
        usage,
        CloudBudgetLimits(
            supabase_max_mb=settings.monitor_supabase_max_mb,
            backblaze_b2_max_mb=settings.monitor_b2_max_mb,
            qdrant_max_points=settings.monitor_qdrant_max_points,
            low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
        ),
    )

    print("CLOUD CAPACITY REPORT - READ ONLY")
    print(f"SUPABASE DATABASE: {_format_bytes(usage.supabase_bytes)}")
    print(f"BACKBLAZE B2 OBJECTS: {_format_bytes(usage.backblaze_b2_bytes)}")
    print(f"QDRANT POINTS: {_format_value(usage.qdrant_points)}")
    for service in services:
        detail = service.detail or "-"
        print(f"{service.service}: state={service.state.value} detail={detail}")
    blockers = ",".join(decision.blocking_services) or "-"
    print(
        f"AUTOMATIC INGESTION CAPACITY: allowed={str(decision.allow_ingestion).lower()} "
        f"reason={decision.reason} blockers={blockers}"
    )
    print("FINAL: READ-ONLY - no evidence, monitor, claim, or trust state was changed.")


if __name__ == "__main__":
    main()
