import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.ingestion.downloader import download_trusted_document
from app.monitoring.auto_ingest_canary import assess_auto_ingest_gate_canary
from app.monitoring.controlled import snapshot_monitoring_database
from app.monitoring.cycle_plan import PendingRetryState, plan_recurring_cycle
from app.monitoring.integrated_cycle import assess_integrated_monitor_stage
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.preflight import preflight_discovered_url
from app.monitoring.processor import (
    _select_eligible_pending_records,
    process_specific_pending_discovery,
)
from app.monitoring.registry import get_monitor
from app.monitoring.runner import probe_monitor_once
from app.services.ingestion import ingest_downloaded_document
from app.storage.database import (
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    SourceMonitorStateRecord,
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
            "Phase 14 one-shot integrated monitor-to-ingestion canary. A due monitor "
            "run is validated and committed first, then at most one retry-eligible "
            "pending discovery is preflighted once and processed from those exact bytes."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    parser.add_argument("--processing-limit", type=int, default=1)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    monitor = get_monitor(args.monitor_id)
    now = datetime.now(UTC)

    print("PHASE 14 INTEGRATED MONITOR -> INGEST CANARY")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print(f"CONFIGURED INTERVAL MINUTES: {monitor.interval_minutes}")
    print(f"PROCESSING LIMIT: {args.processing_limit}")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    if args.processing_limit != 1:
        print("FINAL: BLOCKED - this canary permits exactly one queue item per due cycle.")
        return

    with get_session() as session:
        state = session.get(SourceMonitorStateRecord, monitor.monitor_id)
        last_checked_at = state.last_checked_at if state is not None else None
        consecutive_failures = state.consecutive_failures if state is not None else 0
        pending_before_plan = list(
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
            )
        )
        plan = plan_recurring_cycle(
            monitor,
            now=now,
            last_checked_at=last_checked_at,
            consecutive_failures=consecutive_failures,
            pending_states=tuple(
                PendingRetryState(
                    attempt_count=row.attempt_count,
                    last_attempt_at=row.last_attempt_at,
                    last_error_code=row.last_error_code,
                )
                for row in pending_before_plan
            ),
            processing_limit=args.processing_limit,
        )

        print(f"NOW: {now.isoformat()}")
        print(f"LAST CHECKED AT: {last_checked_at.isoformat() if last_checked_at else '-'}")
        print(
            "MONITOR GATE: "
            f"due={str(plan.monitor_due).lower()} reason={plan.monitor_reason} "
            f"next_eligible={plan.next_monitor_at.isoformat() if plan.next_monitor_at else '-'}"
        )
        print(f"ELIGIBLE PENDING BEFORE MONITOR: {plan.eligible_pending_count}")
        print(f"PLANNED PROCESSING: {plan.planned_processing_count}")

        if not plan.monitor_due:
            session.rollback()
            print(
                "FINAL: PASS-NOT-DUE - cadence guard prevented source access and all "
                "database/B2/Qdrant writes."
            )
            return

        if not args.allow_network or not args.allow_write:
            session.rollback()
            print(
                "FINAL: BLOCKED-DUE - both --allow-network and --allow-write are required "
                "for the one-shot due-cycle canary."
            )
            return
        if not settings.source_monitoring_enabled:
            session.rollback()
            print("FINAL: BLOCKED-DUE - SOURCE_MONITORING_ENABLED must be true.")
            return
        if not settings.source_auto_ingest_enabled:
            session.rollback()
            print("FINAL: BLOCKED-DUE - SOURCE_AUTO_INGEST_ENABLED must be true.")
            return
        if settings.trust_promotion_enabled:
            session.rollback()
            print("FINAL: BLOCKED-DUE - TRUST_PROMOTION_ENABLED must remain false.")
            return

        s3_client = get_s3_client()
        qdrant_client = get_qdrant_client()
        limits = CloudBudgetLimits(
            supabase_max_mb=settings.monitor_supabase_max_mb,
            backblaze_b2_max_mb=settings.monitor_b2_max_mb,
            qdrant_max_points=settings.monitor_qdrant_max_points,
            low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
        )

        usage_before_monitor = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        services, monitor_capacity = assess_measured_capacity(usage_before_monitor, limits)
        for service in services:
            print(
                f"CAPACITY {service.service}: state={service.state.value} "
                f"detail={service.detail or '-'}"
            )
        if not monitor_capacity.allow_ingestion:
            blockers = ",".join(monitor_capacity.blocking_services) or "-"
            session.rollback()
            print(
                "FINAL: BLOCKED-DUE - cloud capacity is not safe before monitor stage. "
                f"reason={monitor_capacity.reason} blockers={blockers}"
            )
            return

        before_monitor_db = snapshot_monitoring_database(session)
        started_at = datetime.now(UTC)
        try:
            downloaded_feed = download_trusted_document(monitor.source_id, monitor.url)
        except ConnectionError:
            session.rollback()
            print("FINAL: BLOCKED-DUE - feed download failed with transient_network_error.")
            return
        except httpx.HTTPError:
            session.rollback()
            print("FINAL: BLOCKED-DUE - feed download failed with http_error.")
            return
        except ValueError:
            session.rollback()
            print("FINAL: BLOCKED-DUE - feed failed source-policy validation.")
            return

        monitor_result = probe_monitor_once(
            session,
            monitor,
            monitor_capacity,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            source_monitoring_enabled=settings.source_monitoring_enabled,
            download_feed=lambda *_: downloaded_feed,
            commit=False,
        )
        staged_monitor_db = snapshot_monitoring_database(session)
        usage_after_monitor = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        monitor_b2_delta = _delta(
            usage_before_monitor.backblaze_b2_bytes,
            usage_after_monitor.backblaze_b2_bytes,
        )
        monitor_qdrant_delta = _delta(
            usage_before_monitor.qdrant_points,
            usage_after_monitor.qdrant_points,
        )
        monitor_decision = assess_integrated_monitor_stage(
            before_monitor_db,
            staged_monitor_db,
            monitor_result,
            source_monitoring_enabled=settings.source_monitoring_enabled,
            source_auto_ingest_enabled=settings.source_auto_ingest_enabled,
            trust_promotion_enabled=settings.trust_promotion_enabled,
            max_new_documents_per_run=monitor.max_new_documents_per_run,
            backblaze_b2_delta=monitor_b2_delta,
            qdrant_points_delta=monitor_qdrant_delta,
        )

        print(
            "MONITOR RUN: "
            f"outcome={monitor_result.outcome.value} reason={monitor_result.reason} "
            f"discovered={monitor_result.discovered_count} "
            f"rejected={monitor_result.rejected_discovery_count}"
        )
        print(
            "MONITOR STAGE DATABASE DELTA: "
            f"documents={staged_monitor_db.documents - before_monitor_db.documents} "
            f"claims={staged_monitor_db.claims - before_monitor_db.claims} "
            f"trust_events={staged_monitor_db.claim_trust_events - before_monitor_db.claim_trust_events} "
            f"discoveries={staged_monitor_db.monitor_discoveries - before_monitor_db.monitor_discoveries} "
            f"monitor_runs={staged_monitor_db.monitor_runs - before_monitor_db.monitor_runs}"
        )
        print(
            "MONITOR STAGE EXTERNAL DELTA: "
            f"backblaze_b2_bytes={monitor_b2_delta} qdrant_points={monitor_qdrant_delta}"
        )

        if not monitor_decision.passed:
            session.rollback()
            print(
                "FINAL: FAIL-ROLLED-BACK - monitor stage did not reconcile; nothing from "
                "the staged monitor transaction was committed. "
                f"blockers={','.join(monitor_decision.blockers) or '-'}"
            )
            return

        session.commit()
        print("MONITOR STAGE: PASS-COMMITTED")

        # Capacity is measured again after the committed monitor stage and before
        # any detail-page preflight or queue processing.
        usage_before_queue = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        _, queue_capacity = assess_measured_capacity(usage_before_queue, limits)
        if not queue_capacity.allow_ingestion:
            blockers = ",".join(queue_capacity.blocking_services) or "-"
            print(
                "FINAL: MONITOR-COMMITTED-QUEUE-BLOCKED - monitor metadata was validly "
                "committed, but capacity became unsafe before queue processing. "
                f"reason={queue_capacity.reason} blockers={blockers}"
            )
            return

        selected = _select_eligible_pending_records(
            session,
            monitor,
            now=datetime.now(UTC),
            limit=1,
        )
        if not selected:
            print(
                "FINAL: PASS-MONITOR-ONLY - the due monitor stage committed safely and "
                "no retry-eligible pending discovery was available for ingestion."
            )
            return

        record = selected[0]
        before_queue_db = snapshot_monitoring_database(session)
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
            f"publication_date={record.publication_date or '-'} "
            f"attempt_count={record.attempt_count}"
        )

        try:
            preflight = preflight_discovered_url(
                record.source_id,
                record.url,
                chunk_size=settings.chunk_size_chars,
                chunk_overlap=settings.chunk_overlap_chars,
                publication_date_hint=record.publication_date,
            )
        except Exception as exc:
            print(
                "FINAL: MONITOR-COMMITTED-QUEUE-BLOCKED - selected evidence failed trusted "
                "preflight; no queue write was attempted. "
                f"error_type={type(exc).__name__}"
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
                raise ValueError("Integrated canary queue item changed after preflight")
            return ingest_downloaded_document(
                preflight.downloaded,
                expected_sha256=preflight.sha256,
            )

        queue_result = process_specific_pending_discovery(
            session,
            monitor,
            queue_capacity,
            record_id=record.id,
            now=datetime.now(UTC),
            source_monitoring_enabled=settings.source_monitoring_enabled,
            source_auto_ingest_enabled=settings.source_auto_ingest_enabled,
            ingest=stable_ingest,
        )

        after_queue_db = snapshot_monitoring_database(session)
        refreshed = session.get(SourceMonitorDiscoveryRecord, record.id)
        usage_after_queue = measure_cloud_usage(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        _, capacity_after = assess_measured_capacity(usage_after_queue, limits)

        supabase_delta = _delta(usage_before_queue.supabase_bytes, usage_after_queue.supabase_bytes)
        b2_delta = _delta(usage_before_queue.backblaze_b2_bytes, usage_after_queue.backblaze_b2_bytes)
        qdrant_delta = _delta(usage_before_queue.qdrant_points, usage_after_queue.qdrant_points)

        queue_decision = assess_auto_ingest_gate_canary(
            before_queue_db,
            after_queue_db,
            queue_result,
            source_monitoring_enabled=settings.source_monitoring_enabled,
            source_auto_ingest_enabled=settings.source_auto_ingest_enabled,
            trust_promotion_enabled=settings.trust_promotion_enabled,
            expected_content_bytes=preflight.content_bytes,
            expected_chunk_count=preflight.chunk_count,
            backblaze_b2_delta=b2_delta,
            qdrant_points_delta=qdrant_delta,
        )
        blockers = list(queue_decision.blockers)

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
                blockers.append("queue:seen_count_changed_during_processing")
            if after_record[4] != before_record[4] + 1:
                blockers.append("queue:attempt_count_not_incremented_once")
            if after_record[5] is not None:
                blockers.append("queue:last_error_code_not_clear")

            expected_status = "ingested" if queue_result.ingested_count == 1 else "duplicate"
            if after_record[1] != expected_status:
                blockers.append("queue:unexpected_terminal_status")
            if not isinstance(after_record[2], str) or not after_record[2]:
                blockers.append("queue:missing_document_link")
            elif (document := session.get(DocumentRecord, after_record[2])) is None:
                blockers.append("database:linked_document_missing")
            elif document.sha256 != preflight.sha256:
                blockers.append("database:linked_document_sha_mismatch")

        if not capacity_after.allow_ingestion:
            blockers.append("capacity:unsafe_after_queue_write")

        print(
            "QUEUE PROCESSING: "
            f"reason={queue_result.reason} selected={queue_result.selected_count} "
            f"ingested={queue_result.ingested_count} duplicate={queue_result.duplicate_count} "
            f"failed={queue_result.failed_count} rejected={queue_result.rejected_count}"
        )
        if refreshed is not None:
            print(
                "QUEUE RESULT: "
                f"status={refreshed.status} error_code={refreshed.last_error_code or '-'} "
                f"attempt_count={refreshed.attempt_count}"
            )
        print(
            "QUEUE DATABASE DELTA: "
            f"documents={after_queue_db.documents - before_queue_db.documents} "
            f"claims={after_queue_db.claims - before_queue_db.claims} "
            f"attributions={after_queue_db.claim_entity_attributions - before_queue_db.claim_entity_attributions} "
            f"supersessions={after_queue_db.claim_supersessions - before_queue_db.claim_supersessions} "
            f"verification_events={after_queue_db.claim_verification_events - before_queue_db.claim_verification_events} "
            f"trust_events={after_queue_db.claim_trust_events - before_queue_db.claim_trust_events}"
        )
        print(
            "QUEUE EXTERNAL DELTA: "
            f"supabase_bytes={supabase_delta} backblaze_b2_bytes={b2_delta} "
            f"qdrant_points={qdrant_delta}"
        )

        if blockers:
            print(
                "FINAL: RECONCILIATION-REQUIRED - monitor metadata was already committed "
                "safely, and the queue attempt completed, but post-write reconciliation "
                "found a mismatch. Existing evidence was preserved. "
                f"blockers={','.join(dict.fromkeys(blockers))}"
            )
            return

        print(
            "FINAL: PASS-COMMITTED - one cadence-eligible monitor discovery run and "
            "exactly one retry-eligible evidence ingestion completed in sequence and "
            "reconciled across queue, PostgreSQL, Backblaze B2, and Qdrant. Trust "
            "promotion remained disabled; no recurring scheduler was enabled."
        )


if __name__ == "__main__":
    main()
