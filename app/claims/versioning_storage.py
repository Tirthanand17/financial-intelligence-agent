from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.versioning import assess_supersession
from app.storage.database import ClaimRecord, ClaimSupersessionRecord


def _record_to_claim(record: ClaimRecord) -> StructuredClaim:
    """Convert a persisted claim row back to the canonical claim model."""
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


def apply_supersession_for_newer_claim(
    session: Session,
    newer_record: ClaimRecord,
    *,
    commit: bool = True,
) -> list[ClaimSupersessionRecord]:
    """Persist safe source-local version transitions for one newer claim.

    The decision remains conservative and is delegated to `assess_supersession`.
    Historical claims are never deleted. When a newer dated claim safely replaces
    an older claim, only the older row's state is changed to `superseded` and an
    audit row is created in `claim_supersessions`.

    Returns only audit rows created during this call. Re-running the operation is
    idempotent because an already-superseded older claim is not transitioned again
    and `older_claim_id` is the audit table primary key.
    """
    newer = _record_to_claim(newer_record)

    older_records = session.scalars(
        select(ClaimRecord).where(
            ClaimRecord.source_id == newer_record.source_id,
            ClaimRecord.id != newer_record.id,
        )
    ).all()

    created: list[ClaimSupersessionRecord] = []

    for older_record in older_records:
        older = _record_to_claim(older_record)
        decision = assess_supersession(older, newer)
        if decision.state is not ClaimState.SUPERSEDED:
            continue

        # A valid supersession decision always carries these values. Keep the
        # guard explicit so persistence never writes incomplete audit history.
        if (
            decision.temporal_kind is None
            or decision.older_date is None
            or decision.newer_date is None
        ):
            continue

        existing = session.scalar(
            select(ClaimSupersessionRecord).where(
                ClaimSupersessionRecord.older_claim_id == older_record.id
            )
        )
        if existing is not None:
            continue

        older_record.state = ClaimState.SUPERSEDED.value
        audit = ClaimSupersessionRecord(
            older_claim_id=older_record.id,
            newer_claim_id=newer_record.id,
            newer_document_id=newer_record.document_id,
            temporal_kind=decision.temporal_kind,
            older_date=decision.older_date,
            newer_date=decision.newer_date,
        )
        session.add(audit)
        created.append(audit)

    if commit:
        session.commit()
        for audit in created:
            session.refresh(audit)
    else:
        session.flush()

    return created
