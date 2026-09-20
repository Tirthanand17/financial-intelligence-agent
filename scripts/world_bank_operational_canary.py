import argparse
import json
import sys
from datetime import UTC, datetime
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
from app.monitoring.world_bank import (
    WORLD_BANK_OPERATIONAL_CONFIRMATION,
    build_world_bank_operational_monitor,
    run_world_bank_operational_once,
)
from app.storage.database import get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run one bounded World Bank operational-monitor canary using the exact-byte "
            "JSON persistence path. This does not activate the production registry."
        )
    )
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if args.confirm != WORLD_BANK_OPERATIONAL_CONFIRMATION:
        raise SystemExit("BLOCKED: exact World Bank operational confirmation is required")

    settings = get_settings()
    monitor = build_world_bank_operational_monitor(enabled=True)
    limits = CloudBudgetLimits(
        supabase_max_mb=settings.monitor_supabase_max_mb,
        backblaze_b2_max_mb=settings.monitor_b2_max_mb,
        qdrant_max_points=settings.monitor_qdrant_max_points,
        low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
    )
    s3_client = get_s3_client()
    qdrant_client = get_qdrant_client()

    with get_session() as session:
        def current_capacity():
            usage = measure_cloud_usage(
                session,
                s3_client=s3_client,
                qdrant_client=qdrant_client,
                s3_bucket=settings.s3_bucket,
                qdrant_collection=settings.qdrant_collection,
            )
            _, decision = assess_measured_capacity(usage, limits)
            return decision

        before = current_capacity()
        result = run_world_bank_operational_once(
            session,
            monitor,
            before,
            now=datetime.now(UTC),
            source_monitoring_enabled=settings.source_monitoring_enabled,
            source_auto_ingest_enabled=settings.source_auto_ingest_enabled,
            trust_promotion_enabled=settings.trust_promotion_enabled,
            allow_network=args.allow_network,
            allow_write=args.allow_write,
            capacity_after=current_capacity,
        )

    payload = {
        "monitor_id": result.monitor_id,
        "outcome": result.outcome.value,
        "reason": result.reason,
        "performed": result.performed,
        "status": result.status,
        "sha256": result.sha256,
        "document_id": result.document_id,
        "chunk_count": result.chunk_count,
        "claim_count": result.claim_count,
        "observation_periods": list(result.observation_periods),
        "blocking_services": list(result.blocking_services),
    }
    print("RESULT_JSON: " + json.dumps(payload, sort_keys=True))

    if not result.performed and result.reason == "monitor_not_due":
        print("FINAL: PASS-NOT-DUE - World Bank cadence guard prevented source access and writes.")
        return
    if result.outcome.value == "success" and result.status == "indexed":
        print("FINAL: PASS-COMMITTED - one bounded World Bank evidence document reconciled.")
        return
    if result.outcome.value == "no_change" and result.status == "already_indexed":
        print("FINAL: PASS-NO-CHANGE - exact World Bank evidence was already reconciled.")
        return

    raise SystemExit(
        "FINAL: BLOCKED - World Bank operational monitor did not complete a safe reconciled cycle."
    )


if __name__ == "__main__":
    main()
