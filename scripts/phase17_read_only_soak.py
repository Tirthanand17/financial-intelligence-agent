import argparse
import resource
import sys
import time
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.soak_readiness import (
    ReadOnlySoakSample,
    assess_read_only_soak,
)
from app.storage.database import (
    ClaimRecord,
    ClaimTrustEventRecord,
    ClaimVerificationEventRecord,
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
    SourceMonitorStateRecord,
    get_session,
)
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


_MIB = 1024 * 1024


def _rss_bytes() -> int:
    # Linux reports ru_maxrss in KiB.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _sample(settings) -> ReadOnlySoakSample:
    with get_session() as session:
        usage = measure_cloud_usage(
            session,
            s3_client=get_s3_client(),
            qdrant_client=get_qdrant_client(),
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        _, capacity = assess_measured_capacity(
            usage,
            CloudBudgetLimits(
                supabase_max_mb=settings.monitor_supabase_max_mb,
                backblaze_b2_max_mb=settings.monitor_b2_max_mb,
                qdrant_max_points=settings.monitor_qdrant_max_points,
                low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
            ),
        )
        sample = ReadOnlySoakSample(
            documents=_count(session, DocumentRecord),
            claims=_count(session, ClaimRecord),
            verification_events=_count(session, ClaimVerificationEventRecord),
            trust_events=_count(session, ClaimTrustEventRecord),
            discoveries=_count(session, SourceMonitorDiscoveryRecord),
            monitor_runs=_count(session, SourceMonitorRunRecord),
            monitor_states=_count(session, SourceMonitorStateRecord),
            backblaze_b2_bytes=usage.backblaze_b2_bytes,
            qdrant_points=usage.qdrant_points,
            capacity_allows_ingestion=capacity.allow_ingestion,
            rss_bytes=_rss_bytes(),
        )
        session.rollback()
        return sample


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded Phase 17 read-only stability soak. Repeatedly samples row counts, "
            "B2 usage, Qdrant points, cloud capacity, and process RSS without writes."
        )
    )
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--interval-seconds", type=float, default=0.0)
    parser.add_argument("--max-rss-growth-mb", type=int, default=64)
    args = parser.parse_args()

    if args.cycles < 2 or args.cycles > 50:
        raise SystemExit("--cycles must be between 2 and 50")
    if args.interval_seconds < 0 or args.interval_seconds > 60:
        raise SystemExit("--interval-seconds must be between 0 and 60")
    if args.max_rss_growth_mb < 0:
        raise SystemExit("--max-rss-growth-mb cannot be negative")

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print("FINAL: BLOCKED - SOURCE_MONITORING_ENABLED must remain false.")
        return
    if settings.source_auto_ingest_enabled:
        print("FINAL: BLOCKED - SOURCE_AUTO_INGEST_ENABLED must remain false.")
        return
    if settings.trust_promotion_enabled:
        print("FINAL: BLOCKED - TRUST_PROMOTION_ENABLED must remain false.")
        return

    print("PHASE 17 BOUNDED READ-ONLY STABILITY SOAK")
    print(f"CYCLES: {args.cycles}")
    print(f"INTERVAL SECONDS: {args.interval_seconds}")
    print(f"MAX RSS GROWTH MIB: {args.max_rss_growth_mb}")
    _sample(settings)  # warm clients/caches before recording the baseline
    samples: list[ReadOnlySoakSample] = []
    for index in range(args.cycles):
        sample = _sample(settings)
        samples.append(sample)
        print(
            f"SAMPLE {index + 1}: docs={sample.documents} claims={sample.claims} "
            f"discoveries={sample.discoveries} runs={sample.monitor_runs} "
            f"b2={sample.backblaze_b2_bytes} qdrant={sample.qdrant_points} "
            f"capacity={str(sample.capacity_allows_ingestion).lower()} "
            f"rss_mib={sample.rss_bytes / _MIB:.2f}"
        )
        if index + 1 < args.cycles and args.interval_seconds:
            time.sleep(args.interval_seconds)

    decision = assess_read_only_soak(
        tuple(samples),
        max_rss_growth_bytes=args.max_rss_growth_mb * _MIB,
    )
    print(f"RSS GROWTH BYTES: {decision.rss_growth_bytes}")
    if not decision.passed:
        print(
            "FINAL: BLOCKED - bounded read-only soak detected instability. "
            f"blockers={','.join(decision.blockers)}"
        )
        return
    print(
        "FINAL: PASS-READ-ONLY - repeated production-state sampling remained stable, "
        "capacity stayed safe, and RSS growth stayed within the configured bound."
    )


if __name__ == "__main__":
    main()
