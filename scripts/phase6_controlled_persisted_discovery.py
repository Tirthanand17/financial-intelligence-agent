import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.controlled import (
    snapshot_monitoring_database,
    validate_controlled_discovery_delta,
)
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.registry import get_monitor
from app.monitoring.runner import download_monitor_payload, probe_monitor_once
from app.storage.database import get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def _delta(old: int, new: int) -> int:
    return new - old


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "One explicit Phase 6 persisted discovery validation. The transaction "
            "may write only monitor audit/state and discovery queue metadata."
        )
    )
    parser.add_argument(
        "--monitor-id",
        default="rbi-press-releases-rss",
        help="Registered monitor ID to validate.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for cloud measurements and one feed fetch.",
    )
    parser.add_argument(
        "--allow-persist-discovery",
        action="store_true",
        help="Required explicit consent to commit only monitor/discovery metadata.",
    )
    args = parser.parse_args()

    if not args.allow_network or not args.allow_persist_discovery:
        print("BLOCKED: no network calls or persistence writes were made.")
        print(
            "Both --allow-network and --allow-persist-discovery are required for "
            "this one-shot controlled validation."
        )
        return

    settings = get_settings()

    # This script is intentionally a one-shot validation while normal automation
    # remains off. If any broader runtime gate is already enabled, refuse to run.
    if settings.source_monitoring_enabled:
        print("BLOCKED: SOURCE_MONITORING_ENABLED must remain false for this one-shot validation.")
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

    print("PHASE 6 CONTROLLED PERSISTED DISCOVERY")
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
                "FINAL: BLOCKED - controlled persistence was not attempted because "
                f"capacity is not safe. reason={capacity.reason} blockers={blockers}"
            )
            session.rollback()
            return

        before = snapshot_monitoring_database(session)
        started_at = datetime.now(UTC)
        try:
            downloaded = download_monitor_payload(monitor.source_id, monitor.url)
        except ConnectionError:
            print("FINAL: BLOCKED - feed download failed with transient_network_error; no writes committed.")
            session.rollback()
            return
        except httpx.HTTPError:
            print("FINAL: BLOCKED - feed download failed with http_error; no writes committed.")
            session.rollback()
            return
        except ValueError:
            print("FINAL: BLOCKED - feed download failed source policy validation; no writes committed.")
            session.rollback()
            return
        finished_at = datetime.now(UTC)

        # Reuse the already downloaded trusted feed inside the transactional
        # runner so there is exactly one source fetch in this validation.
        result = probe_monitor_once(
            session,
            monitor,
            capacity,
            started_at=started_at,
            finished_at=finished_at,
            source_monitoring_enabled=True,
            download_feed=lambda *_: downloaded,
            commit=False,
        )
        staged = snapshot_monitoring_database(session)
        decision = validate_controlled_discovery_delta(
            before,
            staged,
            result,
            max_new_documents_per_run=monitor.max_new_documents_per_run,
        )

        usage_after = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )

        external_blockers: list[str] = []
        if (
            usage_before.backblaze_b2_bytes is None
            or usage_after.backblaze_b2_bytes is None
            or usage_before.backblaze_b2_bytes != usage_after.backblaze_b2_bytes
        ):
            external_blockers.append("backblaze_b2_changed_or_unknown")
        if (
            usage_before.qdrant_points is None
            or usage_after.qdrant_points is None
            or usage_before.qdrant_points != usage_after.qdrant_points
        ):
            external_blockers.append("qdrant_changed_or_unknown")

        print(
            f"RUN: outcome={result.outcome.value} reason={result.reason} "
            f"discovered={result.discovered_count} rejected={result.rejected_discovery_count} "
            f"ingested={result.ingested_count}"
        )
        print(
            "STAGED DATABASE DELTA: "
            f"documents={_delta(before.documents, staged.documents)} "
            f"claims={_delta(before.claims, staged.claims)} "
            f"verification_events={_delta(before.claim_verification_events, staged.claim_verification_events)} "
            f"trust_events={_delta(before.claim_trust_events, staged.claim_trust_events)} "
            f"discoveries={_delta(before.monitor_discoveries, staged.monitor_discoveries)} "
            f"monitor_runs={_delta(before.monitor_runs, staged.monitor_runs)} "
            f"monitor_states={_delta(before.monitor_states, staged.monitor_states)}"
        )
        print(
            "EXTERNAL DELTA: "
            f"backblaze_b2_bytes={None if usage_before.backblaze_b2_bytes is None or usage_after.backblaze_b2_bytes is None else usage_after.backblaze_b2_bytes - usage_before.backblaze_b2_bytes} "
            f"qdrant_points={None if usage_before.qdrant_points is None or usage_after.qdrant_points is None else usage_after.qdrant_points - usage_before.qdrant_points}"
        )

        if not decision.passed or external_blockers:
            blockers = list(decision.blockers) + external_blockers
            session.rollback()
            print(
                "FINAL: FAIL-ROLLED-BACK - staged monitor metadata was not committed. "
                f"blockers={','.join(blockers) or '-'}"
            )
            return

        session.commit()
        print(
            "FINAL: PASS - committed only bounded monitor audit/state and discovery "
            "queue metadata. No document, claim, trust, Backblaze object, or Qdrant "
            "point was created by this run."
        )


if __name__ == "__main__":
    main()
