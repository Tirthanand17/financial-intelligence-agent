from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.monitoring.models import MonitorExecutionResult, MonitorRunOutcome
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    ClaimSupersessionRecord,
    ClaimTrustEventRecord,
    ClaimVerificationEventRecord,
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
    SourceMonitorStateRecord,
)


@dataclass(frozen=True, slots=True)
class MonitoringDatabaseSnapshot:
    documents: int
    claims: int
    claim_entity_attributions: int
    claim_supersessions: int
    claim_verification_events: int
    claim_trust_events: int
    monitor_discoveries: int
    monitor_runs: int
    monitor_states: int


@dataclass(frozen=True, slots=True)
class ControlledPersistenceDecision:
    passed: bool
    reason: str
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryObservation:
    """Small non-secret snapshot used to prove queue re-observation idempotency."""

    record_id: str
    seen_count: int
    status: str
    document_id: str | None


def _count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def snapshot_monitoring_database(session: Session) -> MonitoringDatabaseSnapshot:
    """Read table counts used to prove a discovery-only monitor write boundary."""
    return MonitoringDatabaseSnapshot(
        documents=_count(session, DocumentRecord),
        claims=_count(session, ClaimRecord),
        claim_entity_attributions=_count(session, ClaimEntityAttributionRecord),
        claim_supersessions=_count(session, ClaimSupersessionRecord),
        claim_verification_events=_count(session, ClaimVerificationEventRecord),
        claim_trust_events=_count(session, ClaimTrustEventRecord),
        monitor_discoveries=_count(session, SourceMonitorDiscoveryRecord),
        monitor_runs=_count(session, SourceMonitorRunRecord),
        monitor_states=_count(session, SourceMonitorStateRecord),
    )


def snapshot_discovery_observations(
    session: Session,
    *,
    monitor_id: str,
    urls: tuple[str, ...],
) -> dict[str, DiscoveryObservation]:
    """Snapshot queue identity/counters for an explicit bounded URL set."""
    if not urls:
        return {}

    rows = session.scalars(
        select(SourceMonitorDiscoveryRecord).where(
            SourceMonitorDiscoveryRecord.monitor_id == monitor_id,
            SourceMonitorDiscoveryRecord.url.in_(urls),
        )
    )
    return {
        row.url: DiscoveryObservation(
            record_id=row.id,
            seen_count=row.seen_count,
            status=row.status,
            document_id=row.document_id,
        )
        for row in rows
    }


def validate_idempotent_reobservation(
    before: dict[str, DiscoveryObservation],
    staged: dict[str, DiscoveryObservation],
    *,
    expected_urls: tuple[str, ...],
) -> ControlledPersistenceDecision:
    """Prove that replaying the same feed items updates existing queue rows only.

    A valid re-observation preserves row identity, processing status and linked
    document identity while incrementing ``seen_count`` exactly once. Missing or
    newly created rows are rejected by requiring every expected URL to exist in
    the pre-run snapshot.
    """
    blockers: list[str] = []
    unique_urls = tuple(dict.fromkeys(expected_urls))
    if len(unique_urls) != len(expected_urls):
        blockers.append("reobservation:duplicate_expected_url")

    for url in unique_urls:
        old = before.get(url)
        new = staged.get(url)
        if old is None:
            blockers.append("reobservation:missing_existing_row")
            continue
        if new is None:
            blockers.append("reobservation:row_disappeared")
            continue
        if new.record_id != old.record_id:
            blockers.append("reobservation:row_identity_changed")
        if new.seen_count != old.seen_count + 1:
            blockers.append("reobservation:seen_count_not_incremented_once")
        if new.status != old.status:
            blockers.append("reobservation:status_changed")
        if new.document_id != old.document_id:
            blockers.append("reobservation:document_link_changed")

    if set(staged) != set(unique_urls):
        blockers.append("reobservation:staged_url_set_mismatch")

    if blockers:
        return ControlledPersistenceDecision(
            passed=False,
            reason="idempotent_reobservation_validation_failed",
            blockers=tuple(dict.fromkeys(blockers)),
        )

    return ControlledPersistenceDecision(
        passed=True,
        reason="idempotent_reobservation_validated",
    )


def validate_controlled_discovery_delta(
    before: MonitoringDatabaseSnapshot,
    staged: MonitoringDatabaseSnapshot,
    result: MonitorExecutionResult,
    *,
    max_new_documents_per_run: int,
) -> ControlledPersistenceDecision:
    """Validate staged writes before a one-shot monitor transaction is committed.

    The controlled Phase 6 write may add/update only monitor audit/state and
    discovery-queue metadata. It must not create documents, claims, verification
    events, trust events, or other knowledge-state rows. The monitor runner itself
    never follows discovered item URLs during this step.
    """
    blockers: list[str] = []

    if result.outcome not in {MonitorRunOutcome.SUCCESS, MonitorRunOutcome.NO_CHANGE}:
        blockers.append(f"run:{result.outcome.value}")
    if result.ingested_count != 0:
        blockers.append("run:unexpected_ingestion")
    if result.duplicate_count != 0:
        blockers.append("run:unexpected_processing")

    immutable_counts = (
        ("documents", before.documents, staged.documents),
        ("claims", before.claims, staged.claims),
        (
            "claim_entity_attributions",
            before.claim_entity_attributions,
            staged.claim_entity_attributions,
        ),
        ("claim_supersessions", before.claim_supersessions, staged.claim_supersessions),
        (
            "claim_verification_events",
            before.claim_verification_events,
            staged.claim_verification_events,
        ),
        ("claim_trust_events", before.claim_trust_events, staged.claim_trust_events),
    )
    for name, old, new in immutable_counts:
        if old != new:
            blockers.append(f"database:{name}_changed")

    run_delta = staged.monitor_runs - before.monitor_runs
    if run_delta != 1:
        blockers.append("database:monitor_run_delta_not_one")

    discovery_delta = staged.monitor_discoveries - before.monitor_discoveries
    if discovery_delta < 0 or discovery_delta > max_new_documents_per_run:
        blockers.append("database:discovery_delta_out_of_bounds")

    state_delta = staged.monitor_states - before.monitor_states
    if state_delta not in {0, 1}:
        blockers.append("database:monitor_state_delta_out_of_bounds")

    if blockers:
        return ControlledPersistenceDecision(
            passed=False,
            reason="controlled_persistence_validation_failed",
            blockers=tuple(blockers),
        )

    return ControlledPersistenceDecision(
        passed=True,
        reason="discovery_only_write_boundary_validated",
    )


def validate_single_queue_processing_delta(
    before: MonitoringDatabaseSnapshot,
    after: MonitoringDatabaseSnapshot,
    *,
    selected_count: int,
    ingested_count: int,
    duplicate_count: int,
    failed_count: int,
    rejected_count: int,
) -> ControlledPersistenceDecision:
    """Validate the database boundary for one explicit Phase 7 queue write.

    This validator is intentionally narrow. Exactly one pending discovery may be
    selected, exactly one item must resolve as newly indexed or already indexed,
    the discovery table identity/count must stay stable, monitoring audit/state
    tables must not be changed by the queue processor, and TRUSTED promotion must
    remain impossible while the global trust gate is off.

    Claim, attribution, supersession and verification counts are allowed only to
    increase because the normal trusted ingestion pipeline may derive new audited
    knowledge from the one document.
    """
    blockers: list[str] = []

    if selected_count != 1:
        blockers.append("processing:selected_count_not_one")
    if ingested_count + duplicate_count != 1:
        blockers.append("processing:terminal_success_count_not_one")
    if failed_count != 0:
        blockers.append("processing:failed_count_nonzero")
    if rejected_count != 0:
        blockers.append("processing:rejected_count_nonzero")

    if after.monitor_discoveries != before.monitor_discoveries:
        blockers.append("database:discovery_count_changed")
    if after.monitor_runs != before.monitor_runs:
        blockers.append("database:monitor_run_count_changed")
    if after.monitor_states != before.monitor_states:
        blockers.append("database:monitor_state_count_changed")
    if after.claim_trust_events != before.claim_trust_events:
        blockers.append("database:trust_event_count_changed")

    monotonic_counts = (
        ("documents", before.documents, after.documents),
        ("claims", before.claims, after.claims),
        (
            "claim_entity_attributions",
            before.claim_entity_attributions,
            after.claim_entity_attributions,
        ),
        ("claim_supersessions", before.claim_supersessions, after.claim_supersessions),
        (
            "claim_verification_events",
            before.claim_verification_events,
            after.claim_verification_events,
        ),
    )
    for name, old, new in monotonic_counts:
        if new < old:
            blockers.append(f"database:{name}_decreased")

    document_delta = after.documents - before.documents
    if ingested_count == 1 and document_delta != 1:
        blockers.append("database:new_ingestion_document_delta_not_one")
    if duplicate_count == 1 and document_delta != 0:
        blockers.append("database:duplicate_document_delta_not_zero")

    if blockers:
        return ControlledPersistenceDecision(
            passed=False,
            reason="single_queue_processing_validation_failed",
            blockers=tuple(dict.fromkeys(blockers)),
        )

    return ControlledPersistenceDecision(
        passed=True,
        reason="single_queue_processing_validated",
    )
