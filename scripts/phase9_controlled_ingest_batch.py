import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.batch_processing import (
    BatchWriteObservation,
    assess_bounded_batch_write,
)
from app.monitoring.batch_readiness import (
    BatchPreflightObservation,
    assess_batch_preflight,
)
from app.monitoring.controlled import (
    snapshot_monitoring_database,
    validate_single_queue_processing_delta,
)
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.preflight import DiscoveryPreflightResult, preflight_discovered_url
from app.monitoring.processor import process_specific_pending_discovery
from app.monitoring.registry import get_monitor
from app.services.ingestion import ingest_downloaded_document
from app.storage.database import (
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    get_session,
)
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


MAX_BATCH_LIMIT = 3


def _delta(before: int | None, after: int | None) -> int | None:
    if before is None or after is None:
        return None
    return after - before


def _queue_state(record: SourceMonitorDiscoveryRecord) -> tuple[object, ...]:
    return (
        record.id,
        record.url,
        record.status,
        record.document_id,
        record.seen_count,
        record.attempt_count,
        record.last_error_code,
    )


def _capacity(
    session,
    *,
    s3_client,
    qdrant_client,
    settings,
    limits: CloudBudgetLimits,
):
    usage = measure_cloud_usage(
        session,
        s3_client=s3_client,
        qdrant_client=qdrant_client,
        s3_bucket=settings.s3_bucket,
        qdrant_collection=settings.qdrant_collection,
    )
    services, decision = assess_measured_capacity(usage, limits)
    return usage, services, decision


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 9 controlled ingestion of a small, explicitly approved pending "
            "batch using the exact bytes that passed preflight."
        )
    )
    parser.add_argument("--monitor-id", default="rbi-press-releases-rss")
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Exact number of pending items to process; hard maximum is 3.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Required explicit consent for public-source downloads and cloud checks.",
    )
    parser.add_argument(
        "--allow-write",
        action="store_true",
        help="Required explicit consent to persist this one bounded batch.",
    )
    args = parser.parse_args()

    if not args.allow_network:
        print("BLOCKED: --allow-network is required; no network calls were made.")
        return
    if not args.allow_write:
        print("BLOCKED: --allow-write is required; no persistence was attempted.")
        return
    if args.limit < 1 or args.limit > MAX_BATCH_LIMIT:
        print(f"BLOCKED: --limit must be between 1 and {MAX_BATCH_LIMIT}.")
        return

    settings = get_settings()
    if settings.source_monitoring_enabled:
        print("BLOCKED: SOURCE_MONITORING_ENABLED must remain false during Phase 9.")
        return
    if settings.source_auto_ingest_enabled:
        print("BLOCKED: SOURCE_AUTO_INGEST_ENABLED must remain false during Phase 9.")
        return
    if settings.trust_promotion_enabled:
        print("BLOCKED: TRUST_PROMOTION_ENABLED must remain false during Phase 9.")
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

    print("PHASE 9 CONTROLLED BOUNDED BATCH INGESTION")
    print(f"MONITOR: {monitor.monitor_id} source={monitor.source_id}")
    print("SOURCE_MONITORING_ENABLED: false")
    print("SOURCE_AUTO_INGEST_ENABLED: false")
    print("TRUST_PROMOTION_ENABLED: false")
    print(f"WRITE BOUND: exactly {args.limit} pending discoveries")
    print("EVIDENCE MODE: persist exact preflighted bytes; no second source download")

    with get_session() as session:
        usage_before, services_before, capacity_before = _capacity(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            settings=settings,
            limits=limits,
        )
        for service in services_before:
            print(
                f"CAPACITY {service.service}: state={service.state.value} "
                f"detail={service.detail or '-'}"
            )
        if not capacity_before.allow_ingestion:
            blockers = ",".join(capacity_before.blocking_services) or "-"
            print(
                "FINAL: BLOCKED - cloud capacity is not safe; no batch writes were "
                f"attempted. reason={capacity_before.reason} blockers={blockers}"
            )
            return

        records = list(
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
                .limit(args.limit)
            )
        )
        if len(records) != args.limit:
            print(
                "FINAL: BLOCKED - exact batch size is unavailable; no writes were "
                f"attempted. requested={args.limit} available_selected={len(records)}"
            )
            return

        selected = tuple(
            (record.id, record.url, record.title, record.publication_date)
            for record in records
        )
        queue_before = {record.id: _queue_state(record) for record in records}
        database_before = snapshot_monitoring_database(session)

        preflights: dict[str, DiscoveryPreflightResult] = {}
        preflight_observations: list[BatchPreflightObservation] = []

        # All selected items must pass before the first write is allowed.
        for index, (record_id, url, title, _) in enumerate(selected, start=1):
            try:
                preflight = preflight_discovered_url(
                    monitor.source_id,
                    url,
                    chunk_size=settings.chunk_size_chars,
                    chunk_overlap=settings.chunk_overlap_chars,
                )
            except Exception as exc:
                print(
                    f"PREFLIGHT {index}: status=failed error_type={type(exc).__name__} "
                    f"title={title or '-'}"
                )
                print(
                    "FINAL: BLOCKED-PREFLIGHT - at least one selected item failed "
                    "trusted preflight; no batch writes were attempted."
                )
                return

            preflights[record_id] = preflight
            preflight_observations.append(
                BatchPreflightObservation(
                    record_id=record_id,
                    passed=True,
                    content_bytes=preflight.content_bytes,
                    chunk_count=preflight.chunk_count,
                    eligible_claim_count=preflight.eligible_claim_count,
                    publication_date=preflight.publication_date,
                )
            )
            print(
                f"PREFLIGHT {index}: status=pass title={title or '-'} "
                f"publication_date={preflight.publication_date or '-'} "
                f"bytes={preflight.content_bytes} chunks={preflight.chunk_count} "
                f"eligible_claims={preflight.eligible_claim_count}"
            )

        preflight_decision = assess_batch_preflight(
            tuple(preflight_observations),
            requested_limit=args.limit,
        )
        if not preflight_decision.ready:
            print(
                "FINAL: BLOCKED-PREFLIGHT - bounded batch readiness failed before "
                f"writes. blockers={','.join(preflight_decision.blockers)}"
            )
            return

        write_observations: list[BatchWriteObservation] = []

        for index, (record_id, url, title, _) in enumerate(selected, start=1):
            # Recheck real cloud capacity before every individual write. If a prior
            # item consumed unexpected capacity, the remainder is not attempted.
            usage_item_before, _, capacity_item = _capacity(
                session,
                s3_client=s3_client,
                qdrant_client=qdrant_client,
                settings=settings,
                limits=limits,
            )
            if not capacity_item.allow_ingestion:
                print(
                    "FINAL: STOPPED-PARTIAL - capacity became unsafe before item "
                    f"{index}; prior validated writes were preserved and no later "
                    "items were attempted."
                )
                return

            record = session.get(SourceMonitorDiscoveryRecord, record_id)
            before_state = queue_before[record_id]
            if (
                record is None
                or record.status != "pending"
                or record.url != url
                or _queue_state(record) != before_state
            ):
                print(
                    "FINAL: STOPPED-PARTIAL - selected queue state changed before "
                    f"item {index}; no write was attempted for that item."
                )
                return

            preflight = preflights[record_id]
            item_database_before = snapshot_monitoring_database(session)
            captured_result: dict[str, object] = {}

            def stable_ingest(source_id: str, requested_url: str) -> dict[str, object]:
                if source_id != preflight.source_id or requested_url != preflight.requested_url:
                    raise ValueError("Controlled queue identity changed after preflight")
                result = ingest_downloaded_document(
                    preflight.downloaded,
                    expected_sha256=preflight.sha256,
                )
                captured_result.update(result)
                return result

            processing = process_specific_pending_discovery(
                session,
                monitor,
                capacity_item,
                record_id=record_id,
                now=datetime.now(UTC),
                source_monitoring_enabled=True,
                source_auto_ingest_enabled=True,
                ingest=stable_ingest,
            )
            item_database_after = snapshot_monitoring_database(session)
            refreshed = session.get(SourceMonitorDiscoveryRecord, record_id)

            single_decision = validate_single_queue_processing_delta(
                item_database_before,
                item_database_after,
                selected_count=processing.selected_count,
                ingested_count=processing.ingested_count,
                duplicate_count=processing.duplicate_count,
                failed_count=processing.failed_count,
                rejected_count=processing.rejected_count,
            )
            item_blockers = list(single_decision.blockers)

            if refreshed is None:
                item_blockers.append("queue:record_disappeared")
                queue_status = "missing"
                document_linked = False
                error_code = "record_disappeared"
            else:
                queue_status = refreshed.status
                document_linked = isinstance(refreshed.document_id, str) and bool(refreshed.document_id)
                error_code = refreshed.last_error_code
                if refreshed.seen_count != before_state[4]:
                    item_blockers.append("queue:seen_count_changed")
                if refreshed.attempt_count != before_state[5] + 1:
                    item_blockers.append("queue:attempt_count_not_incremented_once")
                if error_code is not None:
                    item_blockers.append("queue:last_error_code_not_clear")
                if document_linked:
                    document = session.get(DocumentRecord, refreshed.document_id)
                    if document is None:
                        item_blockers.append("database:linked_document_missing")
                    elif document.sha256 != preflight.sha256:
                        item_blockers.append("database:linked_document_sha_mismatch")

            ingestion_status = captured_result.get("status")
            if not isinstance(ingestion_status, str):
                if processing.rejected_count:
                    ingestion_status = "rejected"
                else:
                    ingestion_status = "failed"

            observation = BatchWriteObservation(
                record_id=record_id,
                ingestion_status=ingestion_status,
                queue_status=queue_status,
                content_bytes=preflight.content_bytes,
                chunk_count=preflight.chunk_count,
                document_linked=document_linked,
                error_code=error_code,
            )
            write_observations.append(observation)

            usage_item_after, _, capacity_after_item = _capacity(
                session,
                s3_client=s3_client,
                qdrant_client=qdrant_client,
                settings=settings,
                limits=limits,
            )
            item_b2_delta = _delta(
                usage_item_before.backblaze_b2_bytes,
                usage_item_after.backblaze_b2_bytes,
            )
            item_qdrant_delta = _delta(
                usage_item_before.qdrant_points,
                usage_item_after.qdrant_points,
            )

            if ingestion_status == "indexed":
                if item_b2_delta != preflight.content_bytes:
                    item_blockers.append("external:b2_delta_not_preflight_bytes")
                if item_qdrant_delta != preflight.chunk_count:
                    item_blockers.append("external:qdrant_delta_not_preflight_chunks")
            elif ingestion_status == "already_indexed":
                if item_b2_delta != 0:
                    item_blockers.append("external:duplicate_changed_b2")
                if item_qdrant_delta != 0:
                    item_blockers.append("external:duplicate_changed_qdrant")

            if not capacity_after_item.allow_ingestion:
                item_blockers.append("capacity:unsafe_after_item")

            print(
                f"WRITE {index}: title={title or '-'} ingestion={ingestion_status} "
                f"queue={queue_status} b2_delta={item_b2_delta} "
                f"qdrant_delta={item_qdrant_delta}"
            )

            if item_blockers:
                print(
                    "FINAL: RECONCILIATION-REQUIRED - a bounded item committed but "
                    "post-write validation found a mismatch. Existing evidence was "
                    "preserved and later batch items were not attempted. "
                    f"blockers={','.join(dict.fromkeys(item_blockers))}"
                )
                return

        database_after = snapshot_monitoring_database(session)
        usage_after, _, capacity_after = _capacity(
            session,
            s3_client=s3_client,
            qdrant_client=qdrant_client,
            settings=settings,
            limits=limits,
        )
        batch_decision = assess_bounded_batch_write(
            tuple(write_observations),
            requested_limit=args.limit,
        )

        b2_delta = _delta(usage_before.backblaze_b2_bytes, usage_after.backblaze_b2_bytes)
        qdrant_delta = _delta(usage_before.qdrant_points, usage_after.qdrant_points)
        supabase_delta = _delta(usage_before.supabase_bytes, usage_after.supabase_bytes)

        blockers = list(batch_decision.blockers)
        if database_after.monitor_discoveries != database_before.monitor_discoveries:
            blockers.append("database:discovery_count_changed")
        if database_after.monitor_runs != database_before.monitor_runs:
            blockers.append("database:monitor_run_count_changed")
        if database_after.monitor_states != database_before.monitor_states:
            blockers.append("database:monitor_state_count_changed")
        if database_after.claim_trust_events != database_before.claim_trust_events:
            blockers.append("database:trust_event_count_changed")
        if database_after.documents - database_before.documents != batch_decision.ingested_count:
            blockers.append("database:document_delta_mismatch")

        monotonic = (
            (database_before.claims, database_after.claims, "claims"),
            (
                database_before.claim_entity_attributions,
                database_after.claim_entity_attributions,
                "claim_entity_attributions",
            ),
            (
                database_before.claim_supersessions,
                database_after.claim_supersessions,
                "claim_supersessions",
            ),
            (
                database_before.claim_verification_events,
                database_after.claim_verification_events,
                "claim_verification_events",
            ),
        )
        for old, new, name in monotonic:
            if new < old:
                blockers.append(f"database:{name}_decreased")

        if b2_delta != batch_decision.expected_backblaze_bytes:
            blockers.append("external:batch_b2_delta_mismatch")
        if qdrant_delta != batch_decision.expected_qdrant_points:
            blockers.append("external:batch_qdrant_delta_mismatch")
        if not capacity_after.allow_ingestion:
            blockers.append("capacity:unsafe_after_batch")

        refreshed_rows = {
            row.id: row
            for row in session.scalars(
                select(SourceMonitorDiscoveryRecord).where(
                    SourceMonitorDiscoveryRecord.id.in_(tuple(queue_before))
                )
            )
        }
        for observation in write_observations:
            row = refreshed_rows.get(observation.record_id)
            old = queue_before[observation.record_id]
            if row is None:
                blockers.append("queue:record_disappeared_after_batch")
                continue
            if row.seen_count != old[4]:
                blockers.append("queue:seen_count_changed_after_batch")
            if row.attempt_count != old[5] + 1:
                blockers.append("queue:attempt_count_mismatch_after_batch")
            if row.last_error_code is not None:
                blockers.append("queue:error_code_present_after_batch")

        print(
            "BATCH WRITE RESULT: "
            f"selected={batch_decision.selected_count} "
            f"ingested={batch_decision.ingested_count} "
            f"duplicate={batch_decision.duplicate_count} "
            f"failed={batch_decision.failed_count} rejected={batch_decision.rejected_count}"
        )
        print(
            "DATABASE DELTA: "
            f"documents={database_after.documents - database_before.documents} "
            f"claims={database_after.claims - database_before.claims} "
            f"attributions={database_after.claim_entity_attributions - database_before.claim_entity_attributions} "
            f"supersessions={database_after.claim_supersessions - database_before.claim_supersessions} "
            f"verification_events={database_after.claim_verification_events - database_before.claim_verification_events} "
            f"trust_events={database_after.claim_trust_events - database_before.claim_trust_events}"
        )
        print(
            "EXTERNAL DELTA: "
            f"supabase_bytes={supabase_delta} backblaze_b2_bytes={b2_delta} "
            f"qdrant_points={qdrant_delta}"
        )

        blockers = list(dict.fromkeys(blockers))
        if blockers:
            print(
                "FINAL: RECONCILIATION-REQUIRED - the controlled batch completed "
                "but aggregate validation found a mismatch. Existing evidence was "
                f"preserved. blockers={','.join(blockers)}"
            )
            return

        print(
            "FINAL: PASS-COMMITTED - the exact bounded preflighted batch was "
            "processed and reconciled across queue, PostgreSQL, Backblaze B2, and "
            "Qdrant with zero trust events. Scheduled monitoring and automatic "
            "ingestion remain disabled."
        )


if __name__ == "__main__":
    main()
