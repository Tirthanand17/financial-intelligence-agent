from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.claims.catalog import normalize_indicator_metric
from app.claims.eligibility import claim_quality_rejection_reason
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    ClaimSupersessionRecord,
    ClaimTrustEventRecord,
    ClaimVerificationEventRecord,
    DocumentRecord,
    get_session,
)


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _decode_json_text(value: str | None):
    if not value:
        return []
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def build_document_detail(document_id: str) -> dict[str, object] | None:
    """Return one exact persisted document and its audit graph without writes."""
    document_id = document_id.strip()
    if not document_id:
        raise ValueError("document_id is required")

    with get_session() as session:
        document = session.scalar(select(DocumentRecord).where(DocumentRecord.id == document_id))
        if document is None:
            return None

        claims = list(
            session.scalars(
                select(ClaimRecord)
                .where(ClaimRecord.document_id == document_id)
                .order_by(ClaimRecord.evidence_chunk_index, ClaimRecord.created_at, ClaimRecord.id)
            )
        )
        claim_ids = [row.id for row in claims]

        if claim_ids:
            attributions = list(
                session.scalars(
                    select(ClaimEntityAttributionRecord).where(
                        ClaimEntityAttributionRecord.claim_id.in_(claim_ids)
                    )
                )
            )
            verification_events = list(
                session.scalars(
                    select(ClaimVerificationEventRecord)
                    .where(ClaimVerificationEventRecord.claim_id.in_(claim_ids))
                    .order_by(ClaimVerificationEventRecord.created_at, ClaimVerificationEventRecord.id)
                )
            )
            trust_events = list(
                session.scalars(
                    select(ClaimTrustEventRecord)
                    .where(ClaimTrustEventRecord.claim_id.in_(claim_ids))
                    .order_by(ClaimTrustEventRecord.created_at, ClaimTrustEventRecord.id)
                )
            )
            supersessions = list(
                session.scalars(
                    select(ClaimSupersessionRecord)
                    .where(
                        or_(
                            ClaimSupersessionRecord.older_claim_id.in_(claim_ids),
                            ClaimSupersessionRecord.newer_claim_id.in_(claim_ids),
                        )
                    )
                    .order_by(ClaimSupersessionRecord.created_at)
                )
            )
        else:
            attributions = []
            verification_events = []
            trust_events = []
            supersessions = []

    attribution_by_claim = {row.claim_id: row for row in attributions}
    verification_by_claim: dict[str, list[dict[str, object]]] = {claim_id: [] for claim_id in claim_ids}
    trust_by_claim: dict[str, list[dict[str, object]]] = {claim_id: [] for claim_id in claim_ids}
    supersession_by_claim: dict[str, list[dict[str, object]]] = {claim_id: [] for claim_id in claim_ids}

    for event in verification_events:
        verification_by_claim.setdefault(event.claim_id, []).append(
            {
                "event_id": event.id,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "reason": event.reason,
                "supporting_source_ids": _decode_json_text(event.supporting_source_ids),
                "conflicting_source_ids": _decode_json_text(event.conflicting_source_ids),
                "created_at": _utc_iso(event.created_at),
            }
        )

    for event in trust_events:
        trust_by_claim.setdefault(event.claim_id, []).append(
            {
                "event_id": event.id,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "reason": event.reason,
                "corroborating_source_ids": _decode_json_text(event.corroborating_source_ids),
                "created_at": _utc_iso(event.created_at),
            }
        )

    for edge in supersessions:
        payload = {
            "older_claim_id": edge.older_claim_id,
            "newer_claim_id": edge.newer_claim_id,
            "newer_document_id": edge.newer_document_id,
            "temporal_kind": edge.temporal_kind,
            "older_date": edge.older_date.isoformat(),
            "newer_date": edge.newer_date.isoformat(),
            "created_at": _utc_iso(edge.created_at),
        }
        if edge.older_claim_id in supersession_by_claim:
            supersession_by_claim[edge.older_claim_id].append({**payload, "relation": "superseded_by"})
        if edge.newer_claim_id in supersession_by_claim:
            supersession_by_claim[edge.newer_claim_id].append({**payload, "relation": "supersedes"})

    claim_results: list[dict[str, object]] = []
    for row in claims:
        indicator = normalize_indicator_metric(row.metric)
        quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        attribution = attribution_by_claim.get(row.id)
        claim_results.append(
            {
                "claim_id": row.id,
                "fingerprint": row.fingerprint,
                "source_id": row.source_id,
                "source_url": row.source_url,
                "entity": row.entity,
                "metric": row.metric,
                "canonical_metric": indicator.canonical_metric,
                "indicator_id": indicator.indicator_id,
                "normalization_basis": indicator.basis,
                "value_text": row.value_text,
                "value_numeric": str(row.value_numeric) if row.value_numeric is not None else None,
                "unit": row.unit,
                "publication_date": row.publication_date.isoformat() if row.publication_date else None,
                "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                "evidence_text": row.evidence_text,
                "evidence_chunk_index": row.evidence_chunk_index,
                "confidence": round(float(row.confidence), 4),
                "state": row.state,
                "quality_gate": "pass" if quality_reason is None else "fail",
                "quality_rejection_reason": quality_reason,
                "created_at": _utc_iso(row.created_at),
                "updated_at": _utc_iso(row.updated_at),
                "entity_attribution": (
                    {
                        "canonical_entity": attribution.canonical_entity,
                        "source_default_entity": attribution.source_default_entity,
                        "basis": attribution.basis,
                        "matched_aliases": _decode_json_text(attribution.matched_aliases),
                        "ambiguous_candidates": _decode_json_text(attribution.ambiguous_candidates),
                        "evidence_text": attribution.evidence_text,
                        "created_at": _utc_iso(attribution.created_at),
                    }
                    if attribution is not None
                    else None
                ),
                "verification_events": verification_by_claim.get(row.id, []),
                "trust_events": trust_by_claim.get(row.id, []),
                "supersession_history": supersession_by_claim.get(row.id, []),
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_document_provenance_detail",
        "document": {
            "document_id": document.id,
            "source_id": document.source_id,
            "source_name": document.source_name,
            "source_url": document.source_url,
            "final_url": document.final_url,
            "title": document.title,
            "content_type": document.content_type,
            "sha256": document.sha256,
            "raw_evidence_object_key": document.object_key,
            "retrieved_at": _utc_iso(document.retrieved_at),
            "chunk_count": document.chunk_count,
            "status": document.status,
        },
        "summary": {
            "claims": len(claim_results),
            "entity_attributions": len(attributions),
            "verification_events": len(verification_events),
            "trust_events": len(trust_events),
            "supersession_edges": len(supersessions),
        },
        "claims": claim_results,
        "safety": {
            "read_only": True,
            "mutates_data": False,
            "downloads_raw_object": False,
            "exposes_credentials": False,
            "invented_dates": False,
            "enables_trust_promotion": False,
            "note": (
                "This exact-document view exposes non-secret provenance metadata, including the "
                "private object key reference, only behind dashboard authentication. It never "
                "downloads, rewrites, repairs, promotes, or deletes evidence."
            ),
        },
    }
