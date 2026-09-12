import json
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.trust import assess_trust
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    ClaimTrustEventRecord,
)


def _decode_text_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item) for item in decoded)


def _record_to_claim(
    record: ClaimRecord,
    attribution: ClaimEntityAttributionRecord | None,
) -> StructuredClaim:
    """Rehydrate a persisted claim plus its Phase 3 attribution provenance."""
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
        entity_attribution_basis=(
            attribution.basis if attribution is not None else "unspecified"
        ),
        entity_source_default=(
            attribution.source_default_entity if attribution is not None else None
        ),
        entity_matched_aliases=(
            _decode_text_list(attribution.matched_aliases)
            if attribution is not None
            else ()
        ),
        entity_ambiguous_candidates=(
            _decode_text_list(attribution.ambiguous_candidates)
            if attribution is not None
            else ()
        ),
        entity_evidence_text=(
            attribution.evidence_text if attribution is not None else None
        ),
        confidence=record.confidence,
        state=ClaimState(record.state),
    )


def _comparable_records(session: Session, target: ClaimRecord) -> list[ClaimRecord]:
    """Load one exact entity/metric/unit/temporal peer group."""
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


def _attributions_for_records(
    session: Session,
    records: list[ClaimRecord],
) -> dict[str, ClaimEntityAttributionRecord]:
    claim_ids = [record.id for record in records]
    if not claim_ids:
        return {}

    attributions = session.scalars(
        select(ClaimEntityAttributionRecord).where(
            ClaimEntityAttributionRecord.claim_id.in_(claim_ids)
        )
    ).all()
    return {attribution.claim_id: attribution for attribution in attributions}


def reconcile_trust_for_claim(
    session: Session,
    target_record: ClaimRecord,
    *,
    commit: bool = True,
) -> list[ClaimTrustEventRecord]:
    """Persist a safe VERIFIED -> TRUSTED transition for one primary claim.

    Trust reconciliation is deliberately explicit and target-local. Unlike the
    verification reconciler, this function does not promote the whole peer group:
    only an authority-A direct-primary target can qualify. Secondary corroborating
    claims remain VERIFIED/TRUSTED according to their own independent lifecycle.

    The transition and append-only event are written in one transaction. Repeating
    reconciliation after promotion is idempotent because the target is already
    TRUSTED and therefore creates no second event.
    """
    records = _comparable_records(session, target_record)
    attribution_map = _attributions_for_records(session, records)
    claims = [
        _record_to_claim(record, attribution_map.get(record.id))
        for record in records
    ]

    target_claim = next(
        claim
        for record, claim in zip(records, claims, strict=True)
        if record.id == target_record.id
    )
    decision = assess_trust(target_claim, claims)
    current_state = ClaimState(target_record.state)

    if decision.state is not ClaimState.TRUSTED:
        return []
    if current_state is ClaimState.TRUSTED:
        return []
    if current_state is not ClaimState.VERIFIED:
        return []

    event = ClaimTrustEventRecord(
        id=str(uuid4()),
        claim_id=target_record.id,
        from_state=current_state.value,
        to_state=ClaimState.TRUSTED.value,
        reason=decision.reason,
        corroborating_source_ids=json.dumps(list(decision.corroborating_source_ids)),
    )
    target_record.state = ClaimState.TRUSTED.value
    session.add(event)

    if commit:
        session.commit()
        session.refresh(event)
    else:
        session.flush()

    return [event]


def reconcile_trust_for_peer_group(
    session: Session,
    target_record: ClaimRecord,
    *,
    commit: bool = True,
) -> list[ClaimTrustEventRecord]:
    """Reconcile trust for every active claim in one comparable peer group.

    This helper matters when a corroborating secondary claim arrives after the
    primary claim. Verification can promote both rows during the secondary-source
    ingestion, so trust evaluation must revisit the already-stored authority-A
    primary row rather than evaluating only the newly ingested secondary row.

    The operation is idempotent because each per-claim reconciliation creates an
    event only for a genuine VERIFIED -> TRUSTED transition.
    """
    records = _comparable_records(session, target_record)
    events: list[ClaimTrustEventRecord] = []

    for record in records:
        events.extend(
            reconcile_trust_for_claim(
                session,
                record,
                commit=False,
            )
        )

    if commit:
        session.commit()
        for event in events:
            session.refresh(event)

    return events
