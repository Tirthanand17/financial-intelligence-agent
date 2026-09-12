import json
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.models import StructuredClaim
from app.storage.database import ClaimEntityAttributionRecord, ClaimRecord


def _normalized_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def claim_fingerprint(claim: StructuredClaim) -> str:
    """Build a deterministic identity for one source-backed claim.

    The fingerprint intentionally excludes confidence, state, and entity
    attribution derivation metadata because those can change or be backfilled
    without creating a different underlying fact.
    """
    parts = [
        claim.document_id,
        _normalized_text(claim.source_id),
        _normalized_text(claim.entity),
        _normalized_text(claim.metric),
        _normalized_text(claim.value_text),
        _normalized_text(claim.unit),
        claim.publication_date.isoformat() if claim.publication_date else "",
        claim.effective_date.isoformat() if claim.effective_date else "",
        str(claim.evidence_chunk_index),
        _normalized_text(claim.evidence_text),
    ]
    return sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def find_claim_by_fingerprint(session: Session, fingerprint: str) -> ClaimRecord | None:
    return session.scalar(select(ClaimRecord).where(ClaimRecord.fingerprint == fingerprint))


def save_entity_attribution(
    session: Session,
    record: ClaimRecord,
    claim: StructuredClaim,
) -> tuple[ClaimEntityAttributionRecord | None, bool]:
    """Persist one extraction-time entity attribution decision idempotently.

    Older/manually-created claims use the default `unspecified` basis and do not
    fabricate attribution provenance. If the same claim is later re-derived from
    preserved evidence by the Phase 3 extractor, this helper can backfill the
    missing attribution row without changing the claim's identity.
    """
    if claim.entity_attribution_basis == "unspecified":
        return None, False

    if _normalized_text(record.entity) != _normalized_text(claim.entity):
        raise ValueError("Entity attribution does not match persisted claim entity")

    existing = session.scalar(
        select(ClaimEntityAttributionRecord).where(
            ClaimEntityAttributionRecord.claim_id == record.id
        )
    )
    if existing is not None:
        if _normalized_text(existing.canonical_entity) != _normalized_text(claim.entity):
            raise ValueError("Persisted entity attribution conflicts with claim entity")
        return existing, False

    attribution = ClaimEntityAttributionRecord(
        claim_id=record.id,
        canonical_entity=claim.entity,
        source_default_entity=claim.entity_source_default,
        basis=claim.entity_attribution_basis,
        matched_aliases=json.dumps(list(claim.entity_matched_aliases)),
        ambiguous_candidates=json.dumps(list(claim.entity_ambiguous_candidates)),
        evidence_text=claim.entity_evidence_text,
    )
    session.add(attribution)
    return attribution, True


def save_claim(
    session: Session,
    claim: StructuredClaim,
    *,
    commit: bool = True,
) -> tuple[ClaimRecord, bool]:
    """Persist one claim and any supplied derivation provenance idempotently.

    Returns `(record, created)` so callers can distinguish a new claim from an
    already-known one. Verification/state promotion is deliberately separate.

    `commit=False` lets an ingestion workflow stage claims, attribution
    provenance, document provenance, versioning, and verification in one
    PostgreSQL transaction.
    """
    fingerprint = claim_fingerprint(claim)
    existing = find_claim_by_fingerprint(session, fingerprint)
    if existing is not None:
        _, attribution_created = save_entity_attribution(session, existing, claim)
        if commit and attribution_created:
            session.commit()
        elif not commit and attribution_created:
            session.flush()
        return existing, False

    record = ClaimRecord(
        id=str(uuid4()),
        fingerprint=fingerprint,
        document_id=claim.document_id,
        source_id=claim.source_id,
        source_url=claim.source_url,
        entity=claim.entity,
        metric=claim.metric,
        value_text=claim.value_text,
        value_numeric=claim.value_numeric,
        unit=claim.unit,
        publication_date=claim.publication_date,
        effective_date=claim.effective_date,
        evidence_text=claim.evidence_text,
        evidence_chunk_index=claim.evidence_chunk_index,
        confidence=claim.confidence,
        state=claim.state.value,
    )
    session.add(record)
    save_entity_attribution(session, record, claim)

    if commit:
        session.commit()
        session.refresh(record)
    else:
        # Flush makes staged rows visible to later duplicate/version/verification
        # checks in the same transaction without prematurely committing ingestion.
        session.flush()

    return record, True
