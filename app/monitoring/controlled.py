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
