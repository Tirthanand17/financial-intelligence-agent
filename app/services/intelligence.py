from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.claims.eligibility import claim_quality_rejection_reason
from app.storage.database import ClaimRecord, DocumentRecord, get_session


INACTIVE_STATES = {"rejected", "superseded"}


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _claim_sort_key(row: ClaimRecord) -> tuple[date, datetime]:
    temporal = row.effective_date or row.publication_date or date.min
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return temporal, created


def _claim_item(row: ClaimRecord) -> dict[str, object]:
    evidence = " ".join((row.evidence_text or "").split())
    return {
        "claim_id": row.id,
        "source_id": row.source_id,
        "entity": row.entity,
        "metric": row.metric,
        "value_text": row.value_text,
        "unit": row.unit,
        "state": row.state,
        "confidence": round(float(row.confidence), 4),
        "publication_date": _iso_date(row.publication_date),
        "effective_date": _iso_date(row.effective_date),
        "source_url": row.source_url,
        "evidence_excerpt": evidence[:280],
        "created_at": _iso_datetime(row.created_at),
    }


def build_intelligence_snapshot(*, source_id: str | None = None, limit: int = 12) -> dict[str, object]:
    """Build a read-only evidence intelligence view from persisted project state.

    The snapshot deliberately does not generate new facts, infer market direction,
    promote claim trust, mutate claim state, or invoke a language model. It only
    organizes already-persisted source-grounded evidence and applies the existing
    Phase 16 quality floor when deciding which active claims to surface.
    """
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")

    with get_session() as session:
        claim_stmt = select(ClaimRecord)
        document_stmt = select(DocumentRecord)
        if source_id:
            claim_stmt = claim_stmt.where(ClaimRecord.source_id == source_id)
            document_stmt = document_stmt.where(DocumentRecord.source_id == source_id)

        claims = list(session.scalars(claim_stmt))
        documents = list(session.scalars(document_stmt))

    state_counts = Counter(row.state for row in claims)
    source_document_counts = Counter(row.source_id for row in documents)
    source_claim_counts = Counter(row.source_id for row in claims)

    quality_rejected = [
        row
        for row in claims
        if claim_quality_rejection_reason(row.metric, row.evidence_text) is not None
    ]
    active_quality_safe = [
        row
        for row in claims
        if row.state not in INACTIVE_STATES
        and claim_quality_rejection_reason(row.metric, row.evidence_text) is None
    ]
    active_quality_safe.sort(key=_claim_sort_key, reverse=True)

    conflicts = [row for row in active_quality_safe if row.state == "conflicted"]
    verified_or_trusted = [
        row for row in active_quality_safe if row.state in {"verified", "trusted"}
    ]
    candidates = [row for row in active_quality_safe if row.state == "candidate"]

    recent_documents = sorted(
        documents,
        key=lambda row: row.retrieved_at if row.retrieved_at.tzinfo else row.retrieved_at.replace(tzinfo=UTC),
        reverse=True,
    )[:limit]

    all_sources = sorted(set(source_document_counts) | set(source_claim_counts))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {"source_id": source_id, "limit": limit},
        "summary": {
            "documents": len(documents),
            "claims": len(claims),
            "active_quality_safe_claims": len(active_quality_safe),
            "candidate_claims": len(candidates),
            "verified_or_trusted_claims": len(verified_or_trusted),
            "conflicted_claims": len(conflicts),
            "quality_filtered_claims": len(quality_rejected),
        },
        "claim_states": dict(sorted(state_counts.items())),
        "source_coverage": [
            {
                "source_id": current_source,
                "documents": source_document_counts.get(current_source, 0),
                "claims": source_claim_counts.get(current_source, 0),
            }
            for current_source in all_sources
        ],
        "latest_active_claims": [_claim_item(row) for row in active_quality_safe[:limit]],
        "conflicts": [_claim_item(row) for row in conflicts[:limit]],
        "recent_documents": [
            {
                "document_id": row.id,
                "source_id": row.source_id,
                "title": row.title,
                "source_url": row.source_url,
                "content_type": row.content_type,
                "chunk_count": row.chunk_count,
                "retrieved_at": _iso_datetime(row.retrieved_at),
                "status": row.status,
            }
            for row in recent_documents
        ],
        "interpretation": {
            "verified_or_trusted_available": bool(verified_or_trusted),
            "conflict_attention_required": bool(conflicts),
            "candidate_warning": (
                "Candidate claims are source-grounded but are not independently verified."
            ),
            "safety_note": (
                "This is a read-only evidence organization layer, not a market forecast, "
                "trading signal, or financial recommendation."
            ),
        },
    }
