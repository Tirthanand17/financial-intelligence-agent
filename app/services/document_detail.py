from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select

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


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def build_document_detail(document_id: str) -> dict[str, object] | None:
    """Return one read-only evidence/provenance snapshot for an indexed document."""
    if not document_id or len(document_id) > 128:
        raise ValueError("document_id must be between 1 and 128 characters")

    with get_session() as session:
        document = session.get(DocumentRecord, document_id)
        if document is None:
            return None

        claims = list(
            session.scalars(
                select(ClaimRecord)
                .where(ClaimRecord.document_id == document_id)
                .order_by(ClaimRecord.created_at.asc(), ClaimRecord.id.asc())
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
                    .order_by(ClaimVerificationEventRecord.created_at.asc())
                )
            )
            trust_events = list(
                session.scalars(
                    select(ClaimTrustEventRecord)
                    .where(ClaimTrustEventRecord.claim_id.in_(claim_ids))
                    .order_by(ClaimTrustEventRecord.created_at.asc())
                )
            )
            supersessions = list(
                session.scalars(
                    select(ClaimSupersessionRecord).where(
                        (ClaimSupersessionRecord.older_claim_id.in_(claim_ids))
                        | (ClaimSupersessionRecord.newer_claim_id.in_(claim_ids))
                    )
                )
            )
        else:
            attributions = []
            verification_events = []
            trust_events = []
            supersessions = []

    attribution_by_claim = {row.claim_id: row for row in attributions}
    verification_by_claim: dict[str, list[ClaimVerificationEventRecord]] = defaultdict(list)
    for row in verification_events:
        verification_by_claim[row.claim_id].append(row)
    trust_by_claim: dict[str, list[ClaimTrustEventRecord]] = defaultdict(list)
    for row in trust_events:
        trust_by_claim[row.claim_id].append(row)
    superseded_by = {row.older_claim_id: row for row in supersessions}
    supersedes: dict[str, list[ClaimSupersessionRecord]] = defaultdict(list)
    for row in supersessions:
        supersedes[row.newer_claim_id].append(row)

    claim_items: list[dict[str, object]] = []
    quality_failures = 0
    for claim in claims:
        quality_reason = claim_quality_rejection_reason(claim.metric, claim.evidence_text)
        if quality_reason is not None:
            quality_failures += 1
        attribution = attribution_by_claim.get(claim.id)
        older_edge = superseded_by.get(claim.id)
        newer_edges = sorted(
            supersedes.get(claim.id, []),
            key=lambda item: (item.older_date, item.older_claim_id),
        )

        claim_items.append(
            {
                "claim_id": claim.id,
                "entity": claim.entity,
                "metric": claim.metric,
                "value_text": claim.value_text,
                "value_numeric": str(claim.value_numeric) if claim.value_numeric is not None else None,
                "unit": claim.unit,
                "publication_date": claim.publication_date.isoformat() if claim.publication_date else None,
                "effective_date": claim.effective_date.isoformat() if claim.effective_date else None,
                "state": claim.state,
                "confidence": round(float(claim.confidence), 4),
                "evidence_chunk_index": claim.evidence_chunk_index,
                "evidence_text": claim.evidence_text,
                "quality_gate": "pass" if quality_reason is None else "fail",
                "quality_rejection_reason": quality_reason,
                "created_at": _utc_iso(claim.created_at),
                "updated_at": _utc_iso(claim.updated_at),
                "attribution": (
                    {
                        "canonical_entity": attribution.canonical_entity,
                        "source_default_entity": attribution.source_default_entity,
                        "basis": attribution.basis,
                        "matched_aliases": _json_list(attribution.matched_aliases),
                        "ambiguous_candidates": _json_list(attribution.ambiguous_candidates),
                        "evidence_text": attribution.evidence_text,
                        "created_at": _utc_iso(attribution.created_at),
                    }
                    if attribution is not None
                    else None
                ),
                "verification_events": [
                    {
                        "from_state": event.from_state,
                        "to_state": event.to_state,
                        "reason": event.reason,
                        "supporting_source_ids": _json_list(event.supporting_source_ids),
                        "conflicting_source_ids": _json_list(event.conflicting_source_ids),
                        "created_at": _utc_iso(event.created_at),
                    }
                    for event in verification_by_claim.get(claim.id, [])
                ],
                "trust_events": [
                    {
                        "from_state": event.from_state,
                        "to_state": event.to_state,
                        "reason": event.reason,
                        "corroborating_source_ids": _json_list(event.corroborating_source_ids),
                        "created_at": _utc_iso(event.created_at),
                    }
                    for event in trust_by_claim.get(claim.id, [])
                ],
                "superseded_by": (
                    {
                        "claim_id": older_edge.newer_claim_id,
                        "temporal_kind": older_edge.temporal_kind,
                        "older_date": older_edge.older_date.isoformat(),
                        "newer_date": older_edge.newer_date.isoformat(),
                    }
                    if older_edge is not None
                    else None
                ),
                "supersedes": [
                    {
                        "claim_id": edge.older_claim_id,
                        "temporal_kind": edge.temporal_kind,
                        "older_date": edge.older_date.isoformat(),
                        "newer_date": edge.newer_date.isoformat(),
                    }
                    for edge in newer_edges
                ],
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_document_evidence_detail",
        "document": {
            "document_id": document.id,
            "source_id": document.source_id,
            "source_name": document.source_name,
            "source_url": document.source_url,
            "final_url": document.final_url,
            "title": document.title,
            "content_type": document.content_type,
            "sha256": document.sha256,
            "object_key": document.object_key,
            "retrieved_at": _utc_iso(document.retrieved_at),
            "chunk_count": document.chunk_count,
            "status": document.status,
        },
        "summary": {
            "claims": len(claim_items),
            "quality_failures": quality_failures,
            "verification_events": len(verification_events),
            "trust_events": len(trust_events),
            "supersession_edges": len(supersessions),
        },
        "claims": claim_items,
        "safety": {
            "read_only": True,
            "mutates_data": False,
            "downloads_raw_evidence": False,
            "exposes_provider_credentials": False,
            "note": (
                "This view exposes persisted provenance and derived claim audit history only. "
                "It does not fetch, repair, rewrite, delete, ingest, verify, or promote evidence."
            ),
        },
    }
