import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

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
from app.storage.database import get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def _delta(old: int | None, new: int | None) -> int | None:
    if old is None or new is None:
        return None
    return new - old


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 10 one-shot canary for the real SOURCE_MONITORING_ENABLED gate. "
            "It may persist only monitor audit/state and discovery re-observation "
            "metadata; auto-ingestion and trust promotion must remain disabled."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for cloud measurements and one public feed fetch.",
    )
    parser.add_argument(
        "--allow-monitor-write",
        action="store_true",
        help="Required explicit consent to commit bounded monitor/discovery metadata only.",
    )
    args = parser.parse_args()

    if not args.allow_network or not args.allow_monitor_write:
        print("BLOCKED: both --allow-network and --allow-monitor-write are required.")
        return

    settings = get_settings()
    if not settings.source_monitoring_enabled:
        print(
            "BLOCKED: SOURCE_MONITORING_ENABLED must be true for this Phase 10 gate canary."
        )
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
    limits = CloudBudgetLimits(
        supabase_max_mb=settings.monitor_supabase_max_mb,
        backblaze_b2_max_mb=settings.monitor_b2_max_mb,
        qdrant_max_points=settings.monitor_qdrant_max_points,
        low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
    )

    print("PHASE 10 SOURCE MONITORING GATE CANARY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print("SOURCE_MONITORING_ENABLED: true")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")
    print("WRITE BOUND: monitor audit/state and discovery metadata only")

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
                "FINAL: BLOCKED - monitor canary was not attempted because cloud "
                f"capacity is not safe. reason={capacity.reason} blockers={blockers}"
            )
            return

        before = snapshot_monitoring_database(session)
        started_at = datetime.now(UTC)
        try:
            downloaded = download_trusted_document(monitor.source_id, monitor.url)
        except ConnectionError:
            print("FINAL: BLOCKED - feed download failed with transient_network_error; no writes committed.")
            session.rollback()
            return
        except httpx.HTTPError:
            print("FINAL: BLOCKED - feed download failed with http_error; no writes committed.")
            session.rollback()
            return
        except ValueError:
            print("FINAL: BLOCKED - feed download failed source-policy validation; no writes committed.")
            session.rollback()
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

        decision = assess_monitoring_gate_canary(
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

        if not decision.passed:
            session.rollback()
            print(
                "FINAL: FAIL-ROLLED-BACK - monitoring-gate canary did not reconcile; "
                "staged metadata was not committed. "
                f"blockers={','.join(decision.blockers) or '-'}"
            )
            return

        session.commit()
        print(
            "FINAL: PASS-COMMITTED - the real source-monitoring gate completed one "
            "bounded discovery-only run. Only monitor/discovery metadata was committed; "
            "automatic ingestion and trust promotion remained disabled."
        )


if __name__ == "__main__":
    main()
