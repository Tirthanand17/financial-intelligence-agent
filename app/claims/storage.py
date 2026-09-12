from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.models import StructuredClaim
from app.storage.database import ClaimRecord


def _normalized_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def claim_fingerprint(claim: StructuredClaim) -> str:
    """Build a deterministic identity for one source-backed claim.

    The fingerprint intentionally excludes confidence and state because those
    can change during verification without creating a different underlying fact.
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


def save_claim(
    session: Session,
    claim: StructuredClaim,
    *,
    commit: bool = True,
) -> tuple[ClaimRecord, bool]:
    """Persist one claim idempotently.

    Returns `(record, created)` so callers can distinguish a new claim from an
    already-known one. Verification/state promotion is deliberately separate.

    `commit=False` lets an ingestion workflow stage several claims and the
    document provenance record in one PostgreSQL transaction. The default keeps
    the original standalone behaviour for direct callers and tests.
    """
    fingerprint = claim_fingerprint(claim)
    existing = find_claim_by_fingerprint(session, fingerprint)
    if existing is not None:
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

    if commit:
        session.commit()
        session.refresh(record)
    else:
        # Flush makes the staged row visible to later duplicate checks in the
        # same transaction without prematurely committing the whole ingestion.
        session.flush()

    return record, True
