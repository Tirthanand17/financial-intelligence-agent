import json
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.verification import assess_claim
from app.storage.database import ClaimRecord, ClaimVerificationEventRecord


def _record_to_claim(record: ClaimRecord) -> StructuredClaim:
    return StructuredClaim(
        entity=record.entity,
        metric=record.metric,
        value_text=record.value_text,
        value_numeric=record.value_numeric,
        unit=record.unit,
        publication_date=record.publication_date,
        effective_date=record.effective_date,
        source_id=record.source_id,
        source_url=record.source_url,
        document_id=record.document_id,
        evidence_text=record.evidence_text,
        evidence_chunk_index=record.evidence_chunk_index,
        confidence=record.confidence,
        state=ClaimState(record.state),
    )


def _comparable_records(session: Session, target: ClaimRecord) -> list[ClaimRecord]:
    """Load the smallest safe cross-source comparison group for one claim."""
    if target.effective_date is None and target.publication_date is None:
        return [target]

    conditions = [
        func.lower(ClaimRecord.entity) == target.entity.lower(),
        func.lower(ClaimRecord.metric) == target.metric.lower(),
    ]

    if target.unit is None:
        conditions.append(ClaimRecord.unit.is_(None))
    else:
        conditions.append(func.lower(ClaimRecord.unit) == target.unit.lower())

    if target.effective_date is not None:
        conditions.append(ClaimRecord.effective_date == target.effective_date)
    else:
        conditions.extend(
            [
                ClaimRecord.effective_date.is_(None),
                ClaimRecord.publication_date == target.publication_date,
            ]
        )

    return list(session.scalars(select(ClaimRecord).where(*conditions)))


def reconcile_verification_for_claim(
    session: Session,
    target_record: ClaimRecord,
    *,
    commit: bool = True,
) -> list[ClaimVerificationEventRecord]:
    """Persist safe verification/conflict transitions for a claim's peer group.

    A newly ingested claim can change the assessment of older comparable claims,
    so the whole same-fact temporal group is reconciled together. Automatic
    verification never promotes anything to TRUSTED. Existing TRUSTED claims are
    preserved unless new evidence creates an explicit conflict.

    Only actual state changes create audit events, making repeated reconciliation
    idempotent while preserving a complete append-only transition history.
    """
    records = _comparable_records(session, target_record)
    claims = [_record_to_claim(record) for record in records]
    created: list[ClaimVerificationEventRecord] = []

    for record, claim in zip(records, claims, strict=True):
        decision = assess_claim(claim, claims)
        current_state = ClaimState(record.state)
        next_state = decision.state

        if current_state is ClaimState.TRUSTED and next_state is not ClaimState.CONFLICTED:
            next_state = ClaimState.TRUSTED

        if next_state is current_state:
            continue

        event = ClaimVerificationEventRecord(
            id=str(uuid4()),
            claim_id=record.id,
            from_state=current_state.value,
            to_state=next_state.value,
            reason=decision.reason,
            supporting_source_ids=json.dumps(list(decision.supporting_source_ids)),
            conflicting_source_ids=json.dumps(list(decision.conflicting_source_ids)),
        )
        record.state = next_state.value
        session.add(event)
        created.append(event)

    if commit:
        session.commit()
        for event in created:
            session.refresh(event)
    else:
        session.flush()

    return created
