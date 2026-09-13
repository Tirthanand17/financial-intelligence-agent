import hashlib
import sys
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.core.config import get_settings
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.production_readiness import (
    ProductionReadinessSnapshot,
    assess_production_readiness,
)
from app.monitoring.registry import MONITORS, validate_monitor_registry
from app.monitoring.source_coverage import (
    build_source_coverage,
    primary_india_monitoring_gaps,
)
from app.sources.registry import TRUSTED_SOURCES
from app.storage.database import (
    ClaimRecord,
    ClaimTrustEventRecord,
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
    SourceMonitorStateRecord,
    get_session,
)
from app.storage.object_store import get_raw_document, get_s3_client
from app.storage.vector_store import get_qdrant_client


_VALID_QUEUE_STATUSES = {"pending", "ingested", "duplicate", "rejected"}
_TERMINAL_DOCUMENT_STATUSES = {"ingested", "duplicate"}
_SUCCESSFUL_MONITOR_OUTCOMES = {"success", "no_change"}


def _quality_failed_high_state(claims: list[ClaimRecord]) -> int:
    return sum(
        1
        for claim in claims
        if claim.state in {ClaimState.VERIFIED.value, ClaimState.TRUSTED.value}
        and claim_quality_rejection_reason(claim.metric, claim.evidence_text) is not None
    )


def _queue_metadata_anomalies(records: list[SourceMonitorDiscoveryRecord]) -> int:
    anomalies = 0
    for record in records:
        if record.status not in _VALID_QUEUE_STATUSES:
            anomalies += 1
            continue
        if record.status == "pending" and record.last_error_code is not None:
            if record.attempt_count < 1 or record.last_attempt_at is None:
                anomalies += 1
        if record.status in _TERMINAL_DOCUMENT_STATUSES and record.last_error_code is not None:
            anomalies += 1
    return anomalies


def _linked_document_anomalies(
    records: list[SourceMonitorDiscoveryRecord],
    documents: dict[str, DocumentRecord],
) -> int:
    anomalies = 0
    for record in records:
        if record.status not in _TERMINAL_DOCUMENT_STATUSES:
            continue
        if record.document_id is None:
            anomalies += 1
            continue
        document = documents.get(record.document_id)
        if document is None or document.source_id != record.source_id:
            anomalies += 1
    return anomalies


def _document_integrity_failures(documents: list[DocumentRecord]) -> int:
    failures = 0
    for document in documents:
        if not document.sha256 or document.chunk_count < 1 or not document.object_key:
            failures += 1
            continue
        try:
            payload = get_raw_document(document.object_key)
        except Exception:
            failures += 1
            continue
        if hashlib.sha256(payload).hexdigest() != document.sha256:
            failures += 1
    return failures


def main() -> None:
    settings = get_settings()
    print("PHASE 17 PRODUCTION HARDENING / FINAL READINESS - READ ONLY")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    try:
        validate_monitor_registry()
        registry_valid = True
    except ValueError:
        registry_valid = False
    enabled_monitors = tuple(monitor for monitor in MONITORS if monitor.enabled)
    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    gaps = primary_india_monitoring_gaps(coverage)

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

        states = {
            state.monitor_id: state
            for state in session.scalars(select(SourceMonitorStateRecord))
        }
        ready_monitor_count = 0
        monitors_with_failures = 0
        for monitor in enabled_monitors:
            state = states.get(monitor.monitor_id)
            if state is not None and state.state == "ready":
                ready_monitor_count += 1
            if state is None or state.consecutive_failures:
                monitors_with_failures += 1

        monitors_without_success = 0
        for monitor in enabled_monitors:
            success_count = session.scalar(
                select(func.count())
                .select_from(SourceMonitorRunRecord)
                .where(
                    SourceMonitorRunRecord.monitor_id == monitor.monitor_id,
                    SourceMonitorRunRecord.outcome.in_(_SUCCESSFUL_MONITOR_OUTCOMES),
                )
            )
            if not success_count:
                monitors_without_success += 1

        discoveries = list(session.scalars(select(SourceMonitorDiscoveryRecord)))
        document_rows = list(session.scalars(select(DocumentRecord)))
        document_by_id = {document.id: document for document in document_rows}
        claims = list(session.scalars(select(ClaimRecord)))
        queue_metadata_anomalies = _queue_metadata_anomalies(discoveries)
        linked_document_anomalies = _linked_document_anomalies(
            discoveries,
            document_by_id,
        )
        orphan_claims = sum(
            1 for claim in claims if claim.document_id not in document_by_id
        )
        quality_failed_high_state = _quality_failed_high_state(claims)
        trust_events = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        ) or 0
        expected_qdrant_points = sum(document.chunk_count for document in document_rows)
        document_integrity_failures = _document_integrity_failures(document_rows)
        session.rollback()

    snapshot = ProductionReadinessSnapshot(
        source_monitoring_enabled=settings.source_monitoring_enabled,
        source_auto_ingest_enabled=settings.source_auto_ingest_enabled,
        trust_promotion_enabled=settings.trust_promotion_enabled,
        capacity_allows_ingestion=capacity.allow_ingestion,
        capacity_blockers=capacity.blocking_services,
        required_monitor_count=len(enabled_monitors) if registry_valid else 0,
        ready_monitor_count=ready_monitor_count,
        monitors_without_success=monitors_without_success,
        monitors_with_failures=monitors_with_failures,
        india_authority_a_gaps=len(gaps),
        queue_metadata_anomalies=queue_metadata_anomalies,
        linked_document_anomalies=linked_document_anomalies,
        orphan_claims=orphan_claims,
        document_integrity_failures=document_integrity_failures,
        expected_qdrant_points=expected_qdrant_points,
        actual_qdrant_points=usage.qdrant_points,
        quality_failed_verified_or_trusted=quality_failed_high_state,
        unexpected_trust_events=trust_events,
    )
    decision = assess_production_readiness(snapshot)

    print(
        f"CAPACITY: allowed={str(capacity.allow_ingestion).lower()} "
        f"blockers={','.join(capacity.blocking_services) or '-'}"
    )
    print(
        f"MONITORS: required={snapshot.required_monitor_count} "
        f"ready={snapshot.ready_monitor_count} "
        f"without_success={snapshot.monitors_without_success} "
        f"with_failures={snapshot.monitors_with_failures}"
    )
    print(f"INDIA AUTHORITY-A GAPS: {snapshot.india_authority_a_gaps}")
    print(
        f"QUEUE: metadata_anomalies={snapshot.queue_metadata_anomalies} "
        f"linked_document_anomalies={snapshot.linked_document_anomalies}"
    )
    print(
        f"EVIDENCE: documents={len(document_rows)} "
        f"integrity_failures={snapshot.document_integrity_failures} "
        f"expected_qdrant_points={snapshot.expected_qdrant_points} "
        f"actual_qdrant_points={snapshot.actual_qdrant_points}"
    )
    print(
        f"CLAIMS: total={len(claims)} orphan_claims={snapshot.orphan_claims} "
        f"quality_failed_verified_or_trusted={snapshot.quality_failed_verified_or_trusted}"
    )
    print(f"TRUST EVENTS TOTAL: {snapshot.unexpected_trust_events}")

    if not registry_valid:
        blockers = ("monitor:registry_invalid",) + decision.blockers
    else:
        blockers = decision.blockers

    if blockers:
        print(
            "FINAL: BLOCKED - production readiness invariants are not satisfied. "
            f"blockers={','.join(dict.fromkeys(blockers))}"
        )
        return

    print(
        "FINAL: PASS-READ-ONLY - cloud capacity, monitor readiness, queue metadata, "
        "evidence hashes, document/claim linkage, vector counts, and claim-quality "
        "boundaries are consistent. All automation and trust gates remain disabled."
    )


if __name__ == "__main__":
    main()
