from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select

from app.claims.catalog import normalize_indicator_metric
from app.claims.eligibility import claim_quality_rejection_reason
from app.storage.database import ClaimRecord, DocumentRecord, get_session


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _claim_temporal(row: ClaimRecord) -> tuple[date | None, str]:
    if row.effective_date is not None:
        return row.effective_date, "effective_date"
    if row.publication_date is not None:
        return row.publication_date, "publication_date"
    return None, "undated"


def _contains_literal(column, value: str):
    return func.lower(column).contains(value.casefold(), autoescape=True)


def build_evidence_search_snapshot(
    *,
    q: str | None = None,
    source_id: str | None = None,
    state: str | None = None,
    entity: str | None = None,
    metric: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, object]:
    """Search persisted evidence without mutating, guessing, or crawling.

    Free-text, entity, and metric matching use case-insensitive literal substring
    matching. Source/state filters are exact. Date filters use effective_date when
    present and publication_date otherwise; retrieval timestamps are never used as
    publication/effective dates.
    """
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not 0 <= offset <= 5000:
        raise ValueError("offset must be between 0 and 5000")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")

    q = _clean(q)
    source_id = _clean(source_id)
    state = _clean(state)
    entity = _clean(entity)
    metric = _clean(metric)

    claim_conditions = []
    if source_id is not None:
        claim_conditions.append(ClaimRecord.source_id == source_id)
    if state is not None:
        claim_conditions.append(ClaimRecord.state == state)
    if entity is not None:
        claim_conditions.append(_contains_literal(ClaimRecord.entity, entity))
    if metric is not None:
        claim_conditions.append(_contains_literal(ClaimRecord.metric, metric))
    if q is not None:
        claim_conditions.append(
            or_(
                _contains_literal(ClaimRecord.entity, q),
                _contains_literal(ClaimRecord.metric, q),
                _contains_literal(ClaimRecord.value_text, q),
                _contains_literal(ClaimRecord.evidence_text, q),
                _contains_literal(ClaimRecord.source_url, q),
            )
        )

    temporal_expr = func.coalesce(ClaimRecord.effective_date, ClaimRecord.publication_date)
    if date_from is not None:
        claim_conditions.append(temporal_expr >= date_from)
    if date_to is not None:
        claim_conditions.append(temporal_expr <= date_to)

    document_conditions = []
    if source_id is not None:
        document_conditions.append(DocumentRecord.source_id == source_id)
    if q is not None:
        document_conditions.append(
            or_(
                _contains_literal(func.coalesce(DocumentRecord.title, ""), q),
                _contains_literal(DocumentRecord.source_name, q),
                _contains_literal(DocumentRecord.source_url, q),
                _contains_literal(DocumentRecord.final_url, q),
            )
        )

    with get_session() as session:
        claim_total = session.scalar(
            select(func.count()).select_from(ClaimRecord).where(*claim_conditions)
        ) or 0
        claim_rows = list(
            session.scalars(
                select(ClaimRecord)
                .where(*claim_conditions)
                .order_by(ClaimRecord.created_at.desc(), ClaimRecord.id)
                .offset(offset)
                .limit(limit)
            )
        )

        document_total = session.scalar(
            select(func.count()).select_from(DocumentRecord).where(*document_conditions)
        ) or 0
        document_rows = list(
            session.scalars(
                select(DocumentRecord)
                .where(*document_conditions)
                .order_by(DocumentRecord.retrieved_at.desc(), DocumentRecord.id)
                .offset(offset)
                .limit(limit)
            )
        )

        linked_document_ids = sorted({row.document_id for row in claim_rows})
        linked_documents = (
            list(
                session.scalars(
                    select(DocumentRecord).where(DocumentRecord.id.in_(linked_document_ids))
                )
            )
            if linked_document_ids
            else []
        )

    linked_by_id = {row.id: row for row in linked_documents}

    claim_results: list[dict[str, object]] = []
    for row in claim_rows:
        temporal_date, temporal_basis = _claim_temporal(row)
        quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        indicator = normalize_indicator_metric(row.metric)
        linked = linked_by_id.get(row.document_id)
        claim_results.append(
            {
                "claim_id": row.id,
                "document_id": row.document_id,
                "source_id": row.source_id,
                "entity": row.entity,
                "metric": row.metric,
                "canonical_metric": indicator.canonical_metric,
                "indicator_id": indicator.indicator_id,
                "normalization_basis": indicator.basis,
                "value_text": row.value_text,
                "value_numeric": str(row.value_numeric) if row.value_numeric is not None else None,
                "unit": row.unit,
                "state": row.state,
                "confidence": round(float(row.confidence), 4),
                "publication_date": row.publication_date.isoformat() if row.publication_date else None,
                "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                "temporal_date": temporal_date.isoformat() if temporal_date else None,
                "temporal_basis": temporal_basis,
                "quality_gate": "pass" if quality_reason is None else "fail",
                "quality_rejection_reason": quality_reason,
                "evidence_excerpt": " ".join((row.evidence_text or "").split())[:500],
                "source_url": row.source_url,
                "created_at": _utc_iso(row.created_at),
                "document": (
                    {
                        "title": linked.title,
                        "source_name": linked.source_name,
                        "sha256": linked.sha256,
                        "content_type": linked.content_type,
                        "retrieved_at": _utc_iso(linked.retrieved_at),
                        "chunk_count": linked.chunk_count,
                        "status": linked.status,
                        "source_url": linked.source_url,
                        "final_url": linked.final_url,
                    }
                    if linked is not None
                    else None
                ),
            }
        )

    document_results = [
        {
            "document_id": row.id,
            "source_id": row.source_id,
            "source_name": row.source_name,
            "title": row.title,
            "source_url": row.source_url,
            "final_url": row.final_url,
            "sha256": row.sha256,
            "content_type": row.content_type,
            "retrieved_at": _utc_iso(row.retrieved_at),
            "chunk_count": row.chunk_count,
            "status": row.status,
        }
        for row in document_rows
    ]

    claim_only_filters_active = any(
        value is not None for value in (state, entity, metric, date_from, date_to)
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_persisted_evidence_search",
        "scope": {
            "q": q,
            "source_id": source_id,
            "state": state,
            "entity": entity,
            "metric": metric,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "limit": limit,
            "offset": offset,
        },
        "summary": {
            "claim_hits": int(claim_total),
            "document_hits": int(document_total),
            "returned_claims": len(claim_results),
            "returned_documents": len(document_results),
            "claim_has_more": offset + len(claim_results) < int(claim_total),
            "document_has_more": offset + len(document_results) < int(document_total),
        },
        "claims": claim_results,
        "documents": document_results,
        "search_contract": {
            "text_matching": "case_insensitive_literal_substring",
            "source_filter": "exact",
            "state_filter": "exact",
            "claim_temporal_rule": "effective_date_else_publication_date",
            "direct_document_filters": "q_and_source_only",
            "claim_only_filters_active": claim_only_filters_active,
            "note": (
                "Entity, metric, state, and date filters constrain claim results. "
                "Direct document results use only free text and source because documents do not "
                "carry claim state/entity/metric/publication fields. Linked document provenance "
                "is included on each returned claim when available."
            ),
        },
        "safety": {
            "read_only": True,
            "mutates_data": False,
            "network_crawling": False,
            "fuzzy_matching": False,
            "invented_dates": False,
            "uses_retrieval_time_as_publication_date": False,
            "exposes_object_keys": False,
            "enables_trust_promotion": False,
            "note": (
                "Search is limited to already-persisted evidence and provenance. It never fetches "
                "new sources, changes claim state, promotes trust, repairs stores, or deletes evidence."
            ),
        },
    }
