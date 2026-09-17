from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.claims.catalog import normalize_indicator_metric
from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.storage.database import ClaimRecord, ClaimSupersessionRecord, get_session


# Rejected derived claims are not safe inputs. Superseded claims are deliberately
# retained because this service is historical: an explicit old->new supersession
# edge is itself important evidence of change.
EXCLUDED_STATES = {ClaimState.REJECTED.value}


def _temporal_date(row: ClaimRecord) -> date | None:
    return row.effective_date or row.publication_date


def _created_at(row: ClaimRecord) -> datetime:
    value = row.created_at
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _series_key(row: ClaimRecord) -> tuple[str, str, str | None]:
    resolution = normalize_indicator_metric(row.metric)
    metric_key = resolution.indicator_id or f"exact:{row.metric.casefold()}"
    return (row.entity, metric_key, row.unit)


def _series_label(row: ClaimRecord) -> tuple[str | None, str]:
    resolution = normalize_indicator_metric(row.metric)
    return (resolution.indicator_id, resolution.canonical_metric)


def _sort_key(row: ClaimRecord) -> tuple[date, datetime, str]:
    return (_temporal_date(row) or date.min, _created_at(row), row.id)


def _numeric_delta(previous: ClaimRecord, current: ClaimRecord) -> Decimal | None:
    if previous.value_numeric is None or current.value_numeric is None:
        return None
    if previous.unit != current.unit:
        return None
    return Decimal(current.value_numeric) - Decimal(previous.value_numeric)


def _same_observed_value(previous: ClaimRecord, current: ClaimRecord) -> bool:
    """Compare persisted values conservatively without coercing unlike units."""
    if previous.unit != current.unit:
        return False
    if previous.value_numeric is not None and current.value_numeric is not None:
        return Decimal(previous.value_numeric) == Decimal(current.value_numeric)
    return previous.value_text.strip().casefold() == current.value_text.strip().casefold()


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def build_change_detection_snapshot(
    *,
    source_id: str | None = None,
    entity: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    """Detect factual persisted evidence changes without forecasting or writes.

    Comparisons are exact within one entity + canonical exact-alias indicator (or
    exact source metric when unmapped) + unit series. Quality-safe, dated claims
    participate, including superseded historical claims. Rejected claims do not.
    Unknown dates are never invented and fuzzy metric matching is disabled.
    """
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    with get_session() as session:
        rows = list(session.scalars(select(ClaimRecord)))
        supersessions = list(session.scalars(select(ClaimSupersessionRecord)))

    eligible: list[ClaimRecord] = []
    excluded_reasons: Counter[str] = Counter()
    for row in rows:
        if source_id is not None and row.source_id != source_id:
            continue
        if entity is not None and row.entity != entity:
            continue
        if row.state in EXCLUDED_STATES:
            excluded_reasons["rejected_state"] += 1
            continue
        quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        if quality_reason is not None:
            excluded_reasons[f"quality:{quality_reason}"] += 1
            continue
        if _temporal_date(row) is None:
            excluded_reasons["missing_temporal_scope"] += 1
            continue
        eligible.append(row)

    supersession_edges = {
        (edge.older_claim_id, edge.newer_claim_id): edge for edge in supersessions
    }

    grouped: dict[tuple[str, str, str | None], list[ClaimRecord]] = defaultdict(list)
    for row in eligible:
        grouped[_series_key(row)].append(row)

    events: list[dict[str, object]] = []
    unchanged_confirmations = 0
    for series_rows in grouped.values():
        series_rows.sort(key=_sort_key)
        for previous, current in zip(series_rows, series_rows[1:], strict=False):
            same_value = _same_observed_value(previous, current)
            edge = supersession_edges.get((previous.id, current.id))
            if same_value and edge is None:
                unchanged_confirmations += 1
                continue

            indicator_id, canonical_metric = _series_label(current)
            delta = _numeric_delta(previous, current)
            if edge is not None and same_value:
                change_kind = "supersession_same_value"
            elif edge is not None:
                change_kind = "source_supersession"
            elif delta is not None and delta != 0:
                change_kind = "numeric_value_change"
            else:
                change_kind = "value_text_change"

            direction: str | None = None
            if delta is not None:
                if delta > 0:
                    direction = "increase"
                elif delta < 0:
                    direction = "decrease"
                else:
                    direction = "unchanged"

            events.append(
                {
                    "change_kind": change_kind,
                    "entity": current.entity,
                    "indicator_id": indicator_id,
                    "canonical_metric": canonical_metric,
                    "source_metric_previous": previous.metric,
                    "source_metric_current": current.metric,
                    "unit": current.unit,
                    "previous": {
                        "claim_id": previous.id,
                        "source_id": previous.source_id,
                        "value_text": previous.value_text,
                        "value_numeric": (
                            format(previous.value_numeric, "f")
                            if previous.value_numeric is not None
                            else None
                        ),
                        "temporal_date": _iso_date(_temporal_date(previous)),
                        "publication_date": _iso_date(previous.publication_date),
                        "effective_date": _iso_date(previous.effective_date),
                        "state": previous.state,
                        "source_url": previous.source_url,
                        "evidence_excerpt": " ".join((previous.evidence_text or "").split())[:240],
                    },
                    "current": {
                        "claim_id": current.id,
                        "source_id": current.source_id,
                        "value_text": current.value_text,
                        "value_numeric": (
                            format(current.value_numeric, "f")
                            if current.value_numeric is not None
                            else None
                        ),
                        "temporal_date": _iso_date(_temporal_date(current)),
                        "publication_date": _iso_date(current.publication_date),
                        "effective_date": _iso_date(current.effective_date),
                        "state": current.state,
                        "source_url": current.source_url,
                        "evidence_excerpt": " ".join((current.evidence_text or "").split())[:240],
                    },
                    "numeric_delta": format(delta, "f") if delta is not None else None,
                    "direction": direction,
                    "explicit_supersession": edge is not None,
                }
            )

    events.sort(
        key=lambda item: (
            str(item["current"]["temporal_date"]),
            str(item["entity"]),
            str(item["canonical_metric"]),
        ),
        reverse=True,
    )

    kind_counts = Counter(str(item["change_kind"]) for item in events)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_evidence_change_detection",
        "scope": {"source_id": source_id, "entity": entity, "limit": limit},
        "summary": {
            "persisted_claims": len(rows),
            "eligible_dated_claims": len(eligible),
            "series_compared": len(grouped),
            "detected_changes": len(events),
            "unchanged_confirmations": unchanged_confirmations,
            "returned_changes": min(len(events), limit),
        },
        "change_kind_counts": dict(sorted(kind_counts.items())),
        "excluded_reason_counts": dict(sorted(excluded_reasons.items())),
        "changes": events[:limit],
        "safety": {
            "mutates_data": False,
            "fuzzy_matching_enabled": False,
            "invented_dates": False,
            "generates_forecast": False,
            "generates_trading_signal": False,
            "note": (
                "Changes are comparisons of persisted dated evidence only. "
                "Direction is reported only when comparable numeric values share the same unit. "
                "Superseded claims remain available as historical evidence. "
                "This is factual evidence history, not a forecast or financial recommendation."
            ),
        },
    }
