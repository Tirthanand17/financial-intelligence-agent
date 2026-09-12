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
from app.monitoring.controlled import (
    snapshot_discovery_observations,
    snapshot_monitoring_database,
    validate_controlled_discovery_delta,
    validate_idempotent_reobservation,
)
from app.monitoring.discovery import discover_feed_items
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


_XML_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}


def _delta(old: int, new: int) -> int:
    return new - old


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "One transactional Phase 6 replay proving that an already-persisted "
            "feed observation is idempotent. All staged writes are rolled back."
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
        "--allow-transactional-replay",
        action="store_true",
        help="Required explicit consent to stage queue/audit updates that are always rolled back.",
    )
    args = parser.parse_args()

    if not args.allow_network or not args.allow_transactional_replay:
        print("BLOCKED: no network calls or transactional replay were attempted.")
        print(
            "Both --allow-network and --allow-transactional-replay are required."
        )
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
    s3_client = get_s3_client()
    qdrant_client = get_qdrant_client()

    print("PHASE 6 DISCOVERY IDEMPOTENCY REPLAY - ALWAYS ROLLED BACK")
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
                "FINAL: BLOCKED - capacity is not safe. "
                f"reason={capacity.reason} blockers={blockers}"
            )
            session.rollback()
            return

        try:
            downloaded = download_trusted_document(monitor.source_id, monitor.url)
        except ConnectionError:
            print("FINAL: BLOCKED - feed download failed with transient_network_error.")
            session.rollback()
            return
        except httpx.HTTPError:
            print("FINAL: BLOCKED - feed download failed with http_error.")
            session.rollback()
            return
        except ValueError:
            print("FINAL: BLOCKED - feed download failed source policy validation.")
            session.rollback()
            return

        content_type = downloaded.content_type.split(";", 1)[0].lower()
        if content_type not in _XML_CONTENT_TYPES:
            print("FINAL: BLOCKED - feed content type is not approved XML/RSS/Atom.")
            session.rollback()
            return

        try:
            discovery = discover_feed_items(
                downloaded.content,
                source_id=monitor.source_id,
                limit=monitor.max_new_documents_per_run,
            )
        except ValueError:
            print("FINAL: BLOCKED - feed discovery failed validation.")
            session.rollback()
            return

        expected_urls = tuple(item.url for item in discovery.items)
        if not expected_urls:
            print("FINAL: BLOCKED - current feed contains no allow-listed items.")
            session.rollback()
            return

        before_db = snapshot_monitoring_database(session)
        before_items = snapshot_discovery_observations(
            session,
            monitor_id=monitor.monitor_id,
            urls=expected_urls,
        )
        if set(before_items) != set(expected_urls):
            missing = len(set(expected_urls) - set(before_items))
            print(
                "FINAL: BLOCKED - current feed is not an exact replay of the persisted "
                f"queue; missing_existing_rows={missing}. No replay was committed."
            )
            session.rollback()
            return

        started_at = datetime.now(UTC)
        finished_at = datetime.now(UTC)
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

        staged_db = snapshot_monitoring_database(session)
        staged_items = snapshot_discovery_observations(
            session,
            monitor_id=monitor.monitor_id,
            urls=expected_urls,
        )
        boundary = validate_controlled_discovery_delta(
            before_db,
            staged_db,
            result,
            max_new_documents_per_run=monitor.max_new_documents_per_run,
        )
        replay = validate_idempotent_reobservation(
            before_items,
            staged_items,
            expected_urls=expected_urls,
        )

        usage_after = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )

        blockers: list[str] = list(boundary.blockers) + list(replay.blockers)
        if staged_db.monitor_discoveries != before_db.monitor_discoveries:
            blockers.append("database:new_discovery_row_created")
        if staged_db.monitor_states != before_db.monitor_states:
            blockers.append("database:new_monitor_state_created")
        if result.discovered_count != len(expected_urls):
            blockers.append("run:discovered_count_mismatch")
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
            f"RUN: outcome={result.outcome.value} reason={result.reason} "
            f"discovered={result.discovered_count} rejected={result.rejected_discovery_count} "
            f"ingested={result.ingested_count}"
        )
        print(
            "STAGED DATABASE DELTA: "
            f"documents={_delta(before_db.documents, staged_db.documents)} "
            f"claims={_delta(before_db.claims, staged_db.claims)} "
            f"verification_events={_delta(before_db.claim_verification_events, staged_db.claim_verification_events)} "
            f"trust_events={_delta(before_db.claim_trust_events, staged_db.claim_trust_events)} "
            f"discoveries={_delta(before_db.monitor_discoveries, staged_db.monitor_discoveries)} "
            f"monitor_runs={_delta(before_db.monitor_runs, staged_db.monitor_runs)} "
            f"monitor_states={_delta(before_db.monitor_states, staged_db.monitor_states)}"
        )
        print(
            "REOBSERVATION: "
            f"existing_rows={len(before_items)} identity_preserved={str(replay.passed).lower()}"
        )
        print(
            "EXTERNAL DELTA: "
            f"backblaze_b2_bytes={None if usage_before.backblaze_b2_bytes is None or usage_after.backblaze_b2_bytes is None else usage_after.backblaze_b2_bytes - usage_before.backblaze_b2_bytes} "
            f"qdrant_points={None if usage_before.qdrant_points is None or usage_after.qdrant_points is None else usage_after.qdrant_points - usage_before.qdrant_points}"
        )

        # This validation intentionally never commits, even on success.
        session.rollback()
        if blockers:
            print(
                "FINAL: FAIL-ROLLED-BACK - idempotency validation failed. "
                f"blockers={','.join(dict.fromkeys(blockers))}"
            )
            return

        print(
            "FINAL: PASS-ROLLED-BACK - replay reused the existing discovery rows, "
            "incremented observation counters exactly once in the staged transaction, "
            "created no document/claim/trust/vector/object data, and committed nothing."
        )


if __name__ == "__main__":
    main()
