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
