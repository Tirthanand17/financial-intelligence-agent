import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.controlled import (
    snapshot_monitoring_database,
    validate_single_queue_processing_delta,
)
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.preflight import preflight_discovered_url
from app.monitoring.processor import process_pending_discoveries
from app.monitoring.registry import get_monitor
from app.services.ingestion import ingest_downloaded_document
from app.storage.database import (
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    get_session,
)
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def _delta(before: int | None, after: int | None) -> int | None:
    if before is None or after is None:
        return None
    return after - before


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled Phase 7 processing of exactly one pending discovery. "
            "It preflights one trusted download in memory and, when approved, "
            "persists those exact same validated bytes without downloading again."
        )
    )
    parser.add_argument(
        "--monitor-id",
        default="rbi-press-releases-rss",
        help="Registered monitor ID whose oldest pending item should be processed.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for capacity checks and one public-source download.",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help=(
            "Required explicit consent to persist exactly one validated queue item "
            "through the normal trusted ingestion pipeline."
        ),
    )
    args = parser.parse_args()

    if not args.allow_network:
        print("BLOCKED: --allow-network is required; no network calls were made.")
        return
    if not args.allow_write:
        print("BLOCKED: --allow-write is required; no persistence was attempted.")
        return

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print(
            "BLOCKED: SOURCE_MONITORING_ENABLED must remain false; "
            "this script is the only allowed one-shot processing path."
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

    print("PHASE 7 CONTROLLED SINGLE QUEUE INGESTION")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print("SOURCE_MONITORING_ENABLED: false")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")
    print("WRITE BOUND: exactly one pending discovery")
    print("EVIDENCE MODE: persist exact preflighted bytes; no second source download")

    with get_session() as session:
        usage_before = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        services_before, capacity_before = assess_measured_capacity(usage_before, limits)
        for service in services_before:
            print(
                f"CAPACITY {service.service}: state={service.state.value} "
                f"detail={service.detail or '-'}"
            )
        if not capacity_before.allow_ingestion:
            blockers = ",".join(capacity_before.blocking_services) or "-"
            print(
                "FINAL: BLOCKED - controlled ingestion was not attempted because "
                f"capacity is not safe. reason={capacity_before.reason} blockers={blockers}"
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
            print("FINAL: BLOCKED - no pending discovery is available for controlled ingestion.")
            return

        before_db = snapshot_monitoring_database(session)
        before_record = (
            record.id,
            record.status,
            record.document_id,
            record.seen_count,
            record.attempt_count,
            record.last_error_code,
        )

        print(
            f"QUEUE ITEM: title={record.title or '-'} "
            f"publication_date={record.publication_date or '-'}"
        )

        try:
            preflight = preflight_discovered_url(
                record.source_id,
                record.url,
                chunk_size=settings.chunk_size_chars,
                chunk_overlap=settings.chunk_overlap_chars,
            )
        except Exception as exc:
            # Keep output secret-safe: exception detail can contain provider/network data.
            print(
                "FINAL: BLOCKED - the pending source failed trusted preflight; "
                f"no writes were attempted. error_type={type(exc).__name__}"
            )
            return

        print(
            "PREFLIGHT: "
            f"sha256={preflight.sha256} content_type={preflight.content_type} "
            f"bytes={preflight.content_bytes} chunks={preflight.chunk_count} "
            f"eligible_claims={preflight.eligible_claim_count} "
            f"publication_date={preflight.publication_date or '-'}"
        )

        def stable_ingest(source_id: str, url: str) -> dict[str, object]:
            if source_id != preflight.source_id or url != preflight.requested_url:
                raise ValueError("Controlled queue item changed after preflight")
            return ingest_downloaded_document(
                preflight.downloaded,
                expected_sha256=preflight.sha256,
            )

        result = process_pending_discoveries(
            session,
            monitor,
            capacity_before,
            now=datetime.now(UTC),
            source_monitoring_enabled=True,
            source_auto_ingest_enabled=True,
            limit=1,
            ingest=stable_ingest,
        )

        # process_pending_discoveries commits the queue transition. From this point
        # onward the script only reconciles what was actually persisted; it never
        # silently deletes evidence after a partial cross-store outcome.
        after_db = snapshot_monitoring_database(session)
        refreshed = session.get(SourceMonitorDiscoveryRecord, record.id)
        usage_after = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        services_after, capacity_after = assess_measured_capacity(usage_after, limits)

        b2_delta = _delta(usage_before.backblaze_b2_bytes, usage_after.backblaze_b2_bytes)
        qdrant_delta = _delta(usage_before.qdrant_points, usage_after.qdrant_points)
        supabase_delta = _delta(usage_before.supabase_bytes, usage_after.supabase_bytes)

        print(
            "PROCESSING: "
            f"reason={result.reason} selected={result.selected_count} "
            f"ingested={result.ingested_count} duplicate={result.duplicate_count} "
            f"failed={result.failed_count} rejected={result.rejected_count}"
        )
        if refreshed is not None:
            print(
                "QUEUE RESULT: "
                f"status={refreshed.status} error_code={refreshed.last_error_code or '-'} "
                f"attempt_count={refreshed.attempt_count}"
            )
        print(
            "DATABASE DELTA: "
            f"documents={after_db.documents - before_db.documents} "
            f"claims={after_db.claims - before_db.claims} "
            f"attributions={after_db.claim_entity_attributions - before_db.claim_entity_attributions} "
            f"supersessions={after_db.claim_supersessions - before_db.claim_supersessions} "
            f"verification_events={after_db.claim_verification_events - before_db.claim_verification_events} "
            f"trust_events={after_db.claim_trust_events - before_db.claim_trust_events}"
        )
        print(
            "EXTERNAL DELTA: "
            f"supabase_bytes={supabase_delta} "
            f"backblaze_b2_bytes={b2_delta} qdrant_points={qdrant_delta}"
        )

        blockers: list[str] = []
        decision = validate_single_queue_processing_delta(
            before_db,
            after_db,
            selected_count=result.selected_count,
            ingested_count=result.ingested_count,
            duplicate_count=result.duplicate_count,
            failed_count=result.failed_count,
            rejected_count=result.rejected_count,
        )
        blockers.extend(decision.blockers)

        if refreshed is None:
            blockers.append("queue:record_disappeared")
        else:
            after_record = (
                refreshed.id,
                refreshed.status,
                refreshed.document_id,
                refreshed.seen_count,
                refreshed.attempt_count,
                refreshed.last_error_code,
            )
            if after_record[0] != before_record[0]:
                blockers.append("queue:row_identity_changed")
            if after_record[3] != before_record[3]:
                blockers.append("queue:seen_count_changed")
            if after_record[4] != before_record[4] + 1:
                blockers.append("queue:attempt_count_not_incremented_once")
            if after_record[5] is not None:
                blockers.append("queue:last_error_code_not_clear")

            expected_status = "ingested" if result.ingested_count == 1 else "duplicate"
            if after_record[1] != expected_status:
                blockers.append("queue:unexpected_terminal_status")
            if not isinstance(after_record[2], str) or not after_record[2]:
                blockers.append("queue:missing_document_link")

            if isinstance(after_record[2], str) and after_record[2]:
                document = session.get(DocumentRecord, after_record[2])
                if document is None:
                    blockers.append("database:linked_document_missing")
                elif document.sha256 != preflight.sha256:
                    blockers.append("database:linked_document_sha_mismatch")

        if usage_after.backblaze_b2_bytes is None:
            blockers.append("external:backblaze_usage_unknown")
        if usage_after.qdrant_points is None:
            blockers.append("external:qdrant_usage_unknown")

        if result.ingested_count == 1:
            if b2_delta != preflight.content_bytes:
                blockers.append("external:b2_delta_not_preflight_bytes")
            if qdrant_delta != preflight.chunk_count:
                blockers.append("external:qdrant_delta_not_preflight_chunks")
        elif result.duplicate_count == 1:
            if b2_delta != 0:
                blockers.append("external:duplicate_changed_b2")
            if qdrant_delta != 0:
                blockers.append("external:duplicate_changed_qdrant")

        if not capacity_after.allow_ingestion:
            blockers.append("capacity:unsafe_after_write")

        if blockers:
            print(
                "FINAL: RECONCILIATION-REQUIRED - the one-item operation completed "
                "but post-write validation found a mismatch. Existing data was preserved; "
                f"nothing was silently deleted. blockers={','.join(dict.fromkeys(blockers))}"
            )
            return

        print(
            "FINAL: PASS-COMMITTED - exactly one preflighted pending discovery was "
            "processed through trusted ingestion using the exact preflighted bytes, "
            "queue linkage and cross-store deltas reconciled, and no trust event was created."
        )


if __name__ == "__main__":
    main()
