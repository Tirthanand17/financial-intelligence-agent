from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, or_, select

from app.claims.eligibility import claim_quality_rejection_reason
from app.services.change_detection import build_change_detection_snapshot
from app.services.incidents import build_incident_snapshot
from app.storage.database import ClaimRecord, DocumentRecord, get_session


INACTIVE_STATES = {"rejected", "superseded"}


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _claim_temporal_date(row: ClaimRecord) -> date | None:
    return row.effective_date or row.publication_date


def _claim_item(row: ClaimRecord) -> dict[str, object]:
    return {
        "claim_id": row.id,
        "source_id": row.source_id,
        "entity": row.entity,
        "metric": row.metric,
        "value_text": row.value_text,
        "unit": row.unit,
        "state": row.state,
        "confidence": round(float(row.confidence), 4),
        "temporal_date": _iso_date(_claim_temporal_date(row)),
        "publication_date": _iso_date(row.publication_date),
        "effective_date": _iso_date(row.effective_date),
        "source_url": row.source_url,
        "evidence_excerpt": " ".join((row.evidence_text or "").split())[:280],
    }


def _temporal_window_clause(cutoff_date: date):
    # Preserve project temporal semantics exactly: effective_date takes
    # precedence. Publication date participates only when effective_date is absent.
    return or_(
        ClaimRecord.effective_date >= cutoff_date,
        and_(
            ClaimRecord.effective_date.is_(None),
            ClaimRecord.publication_date >= cutoff_date,
        ),
    )


def build_intelligence_digest(
    *,
    lookback_days: int = 1,
    limit: int = 20,
    now: datetime | None = None,
) -> dict[str, object]:
    """Build a deterministic factual digest from persisted evidence only.

    The digest is a read-only projection. It never invokes a language model,
    fetches external sources, mutates state, promotes trust, or generates market
    forecasts/trading recommendations. Missing temporal scope remains missing.

    The bounded lookback is also pushed into SQL so the digest does not load the
    complete document/claim history merely to discard old rows in Python.
    """
    if not 1 <= lookback_days <= 30:
        raise ValueError("lookback_days must be between 1 and 30")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")

    generated_at = now or datetime.now(UTC)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    generated_at = generated_at.astimezone(UTC)
    cutoff_datetime = generated_at - timedelta(days=lookback_days)
    cutoff_date = cutoff_datetime.date()

    temporal_window = _temporal_window_clause(cutoff_date)
    with get_session() as session:
        recent_document_count = int(
            session.scalar(
                select(func.count())
                .select_from(DocumentRecord)
                .where(DocumentRecord.retrieved_at >= cutoff_datetime)
            )
            or 0
        )
        recent_documents = list(
            session.scalars(
                select(DocumentRecord)
                .where(DocumentRecord.retrieved_at >= cutoff_datetime)
                .order_by(DocumentRecord.retrieved_at.desc(), DocumentRecord.id.desc())
                .limit(limit)
            )
        )
        claims = list(
            session.scalars(
                select(ClaimRecord)
                .where(temporal_window)
                .where(ClaimRecord.state.not_in(INACTIVE_STATES))
                .order_by(
                    ClaimRecord.effective_date.desc().nullslast(),
                    ClaimRecord.publication_date.desc().nullslast(),
                    ClaimRecord.created_at.desc(),
                    ClaimRecord.id.desc(),
                )
            )
        )

    new_claims: list[ClaimRecord] = []
    conflicts: list[ClaimRecord] = []
    for row in claims:
        # Quality remains an evidence-text policy and is deliberately evaluated by
        # the existing canonical quality function after the SQL temporal/state
        # pushdown. No historical row is changed or deleted.
        if claim_quality_rejection_reason(row.metric, row.evidence_text) is not None:
            continue
        new_claims.append(row)
        if row.state == "conflicted":
            conflicts.append(row)

    new_claims.sort(
        key=lambda row: (_claim_temporal_date(row) or date.min, row.created_at, row.id),
        reverse=True,
    )
    conflicts.sort(
        key=lambda row: (_claim_temporal_date(row) or date.min, row.created_at, row.id),
        reverse=True,
    )

    change_snapshot = build_change_detection_snapshot(limit=500)
    changes = [
        item
        for item in change_snapshot["changes"]
        if item.get("current", {}).get("temporal_date")
        and str(item["current"]["temporal_date"]) >= cutoff_date.isoformat()
    ][:limit]

    incident_snapshot = build_incident_snapshot()

    return {
        "generated_at": generated_at.isoformat(),
        "mode": "read_only_intelligence_digest",
        "window": {
            "lookback_days": lookback_days,
            "cutoff_datetime": cutoff_datetime.isoformat(),
            "cutoff_date": cutoff_date.isoformat(),
        },
        "summary": {
            "recent_documents": recent_document_count,
            "new_quality_safe_active_claims": len(new_claims),
            "detected_changes": len(changes),
            "conflicted_claims": len(conflicts),
            "operator_incidents": int(incident_snapshot["summary"]["incidents"]),
            "critical_incidents": int(incident_snapshot["summary"]["critical"]),
            "high_incidents": int(incident_snapshot["summary"]["high"]),
        },
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
        "new_evidence": [_claim_item(row) for row in new_claims[:limit]],
        "changes": changes,
        "conflicts": [_claim_item(row) for row in conflicts[:limit]],
        "incidents": incident_snapshot["incidents"][:limit],
        "incident_status": incident_snapshot["status"],
        "performance": {
            "document_history_full_scan": False,
            "claim_history_full_scan": False,
            "document_rows_materialized_at_most": limit,
            "claim_query_temporally_bounded": True,
        },
        "safety": {
            "read_only": True,
            "mutates_data": False,
            "fetches_external_sources": False,
            "invokes_language_model": False,
            "invented_dates": False,
            "generates_forecast": False,
            "generates_trading_signal": False,
            "sends_external_notifications": False,
            "note": (
                "Digest content is a deterministic summary of persisted evidence, factual changes, conflicts, "
                "and operator incidents inside the selected lookback window. Missing dates are not invented. "
                "It is not a forecast, recommendation, or trading signal."
            ),
        },
    }
