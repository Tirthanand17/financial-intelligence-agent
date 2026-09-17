from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.claims.eligibility import claim_quality_rejection_reason
from app.sources.registry import get_source
from app.storage.database import ClaimRecord, ClaimSupersessionRecord, get_session


INACTIVE_STATES = {"rejected", "superseded"}


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _date_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _temporal_date(row: ClaimRecord) -> date | None:
    return row.effective_date or row.publication_date


def _created_key(row: ClaimRecord) -> datetime:
    value = row.created_at
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _point_sort_key(row: ClaimRecord) -> tuple[int, date, datetime, str]:
    temporal = _temporal_date(row)
    # Unknown temporal scope stays separate and sorts after dated evidence.
    return (
        0 if temporal is not None else 1,
        temporal or date.max,
        _created_key(row),
        row.id,
    )


def _source_name(source_id: str) -> str:
    try:
        return get_source(source_id).name
    except ValueError:
        return source_id


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def build_timeline_snapshot(
    *,
    entity: str | None = None,
    metric: str | None = None,
    source_id: str | None = None,
    series_limit: int = 20,
    points_per_series: int = 30,
) -> dict[str, object]:
    """Build a read-only chronological view of persisted structured claims.

    Dates are never invented. A point without publication/effective date remains
    explicitly undated. The service performs no forecasting, state transition,
    trust promotion, source fetch, or persistence write.
    """
    if not 1 <= series_limit <= 50:
        raise ValueError("series_limit must be between 1 and 50")
    if not 1 <= points_per_series <= 100:
        raise ValueError("points_per_series must be between 1 and 100")

    with get_session() as session:
        all_claims = list(session.scalars(select(ClaimRecord)))
        supersessions = list(session.scalars(select(ClaimSupersessionRecord)))

    available_entities = sorted({row.entity for row in all_claims})
    available_metrics = sorted({row.metric for row in all_claims})
    available_sources = sorted({row.source_id for row in all_claims})

    filtered = [
        row
        for row in all_claims
        if (entity is None or row.entity == entity)
        and (metric is None or row.metric == metric)
        and (source_id is None or row.source_id == source_id)
    ]

    supersession_by_older = {row.older_claim_id: row for row in supersessions}
    superseded_by_newer: dict[str, list[ClaimSupersessionRecord]] = defaultdict(list)
    for row in supersessions:
        superseded_by_newer[row.newer_claim_id].append(row)

    grouped: dict[tuple[str, str, str | None], list[ClaimRecord]] = defaultdict(list)
    for row in filtered:
        grouped[(row.entity, row.metric, row.unit)].append(row)

    series_rows: list[dict[str, object]] = []
    total_quality_safe = 0
    total_undated = 0
    total_conflicted = 0

    for (series_entity, series_metric, unit), rows in grouped.items():
        rows.sort(key=_point_sort_key)
        quality_safe_count = sum(
            1
            for row in rows
            if claim_quality_rejection_reason(row.metric, row.evidence_text) is None
        )
        undated_count = sum(1 for row in rows if _temporal_date(row) is None)
        conflicted_count = sum(1 for row in rows if row.state == "conflicted")
        total_quality_safe += quality_safe_count
        total_undated += undated_count
        total_conflicted += conflicted_count

        active_rows = [row for row in rows if row.state not in INACTIVE_STATES]
        latest_active = max(
            active_rows,
            key=lambda row: (
                _temporal_date(row) or date.min,
                _created_key(row),
            ),
            default=None,
        )
        dated_rows = [row for row in rows if _temporal_date(row) is not None]
        latest_temporal = max((_temporal_date(row) for row in dated_rows), default=None)

        points: list[dict[str, object]] = []
        for row in rows[-points_per_series:]:
            quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
            supersession = supersession_by_older.get(row.id)
            supersedes = sorted(
                superseded_by_newer.get(row.id, []),
                key=lambda item: (item.older_date, item.older_claim_id),
            )
            points.append(
                {
                    "claim_id": row.id,
                    "temporal_date": _date_iso(_temporal_date(row)),
                    "temporal_basis": (
                        "effective_date"
                        if row.effective_date is not None
                        else "publication_date"
                        if row.publication_date is not None
                        else "undated"
                    ),
                    "publication_date": _date_iso(row.publication_date),
                    "effective_date": _date_iso(row.effective_date),
                    "source_id": row.source_id,
                    "source_name": _source_name(row.source_id),
                    "source_url": row.source_url,
                    "value_text": row.value_text,
                    "value_numeric": _decimal_text(row.value_numeric),
                    "unit": row.unit,
                    "state": row.state,
                    "confidence": round(float(row.confidence), 4),
                    "quality_gate": "pass" if quality_reason is None else "fail",
                    "quality_rejection_reason": quality_reason,
                    "superseded_by_claim_id": (
                        supersession.newer_claim_id if supersession is not None else None
                    ),
                    "supersedes_claim_ids": [item.older_claim_id for item in supersedes],
                    "evidence_excerpt": " ".join((row.evidence_text or "").split())[:280],
                    "created_at": _utc_iso(row.created_at),
                }
            )

        series_rows.append(
            {
                "entity": series_entity,
                "metric": series_metric,
                "unit": unit,
                "point_count": len(rows),
                "returned_point_count": len(points),
                "quality_safe_points": quality_safe_count,
                "undated_points": undated_count,
                "conflicted_points": conflicted_count,
                "latest_temporal_date": _date_iso(latest_temporal),
                "latest_active": (
                    {
                        "claim_id": latest_active.id,
                        "value_text": latest_active.value_text,
                        "source_id": latest_active.source_id,
                        "state": latest_active.state,
                        "temporal_date": _date_iso(_temporal_date(latest_active)),
                    }
                    if latest_active is not None
                    else None
                ),
                "points": points,
            }
        )

    series_rows.sort(
        key=lambda item: (
            item["latest_temporal_date"] is None,
            item["latest_temporal_date"] or "9999-12-31",
            str(item["entity"]),
            str(item["metric"]),
        ),
        reverse=False,
    )
    # Newest dated series first, undated-only series last.
    dated_series = [item for item in series_rows if item["latest_temporal_date"] is not None]
    undated_series = [item for item in series_rows if item["latest_temporal_date"] is None]
    dated_series.sort(key=lambda item: str(item["latest_temporal_date"]), reverse=True)
    undated_series.sort(key=lambda item: (str(item["entity"]), str(item["metric"])))
    ordered_series = (dated_series + undated_series)[:series_limit]

    state_counts = Counter(row.state for row in filtered)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_evidence_timeline",
        "scope": {
            "entity": entity,
            "metric": metric,
            "source_id": source_id,
            "series_limit": series_limit,
            "points_per_series": points_per_series,
        },
        "summary": {
            "claims_in_scope": len(filtered),
            "series_in_scope": len(series_rows),
            "series_returned": len(ordered_series),
            "quality_safe_claims": total_quality_safe,
            "undated_claims": total_undated,
            "conflicted_claims": total_conflicted,
        },
        "state_counts": dict(sorted(state_counts.items())),
        "facets": {
            "entities": available_entities,
            "metrics": available_metrics,
            "sources": [
                {"source_id": sid, "source_name": _source_name(sid)}
                for sid in available_sources
            ],
        },
        "series": ordered_series,
        "safety": {
            "invented_dates": False,
            "mutates_data": False,
            "generates_forecast": False,
            "generates_trading_signal": False,
            "note": (
                "Timeline ordering uses only persisted effective/publication dates. "
                "Undated claims remain explicitly undated. This is evidence history, "
                "not a forecast or financial recommendation."
            ),
        },
    }
