from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import select

from app.claims.catalog import catalog_definitions, normalize_indicator_metric
from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.storage.database import ClaimRecord, get_session


def _latest_sort_key(row: ClaimRecord) -> tuple[int, object, object, str]:
    if row.effective_date is not None:
        return (2, row.effective_date, row.created_at, row.id)
    if row.publication_date is not None:
        return (1, row.publication_date, row.created_at, row.id)
    return (0, row.created_at.date(), row.created_at, row.id)


def build_indicator_catalog_snapshot(*, limit: int = 100) -> dict[str, object]:
    """Overlay a conservative canonical indicator catalog on persisted claims.

    This function is intentionally read-only. It never rewrites the persisted
    metric label and never guesses an unknown metric through fuzzy matching.
    Canonicalization is an exact alias overlay for analysis and navigation only.
    """
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    with get_session() as session:
        rows = list(session.scalars(select(ClaimRecord)))

    definitions = catalog_definitions()
    by_indicator: dict[str, list[ClaimRecord]] = defaultdict(list)
    unmapped_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    mapped_count = 0
    quality_safe_mapped = 0

    mapping_rows: list[dict[str, object]] = []
    terminal = {ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value}

    for row in rows:
        resolution = normalize_indicator_metric(row.metric)
        quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        unit_matches = (
            True
            if not resolution.expected_units or row.unit is None
            else row.unit in resolution.expected_units
        )

        if resolution.indicator_id is None:
            unmapped_counts[resolution.source_metric] += 1
        else:
            mapped_count += 1
            by_indicator[resolution.indicator_id].append(row)
            if resolution.category:
                category_counts[resolution.category] += 1
            if quality_reason is None and row.state not in terminal:
                quality_safe_mapped += 1

        mapping_rows.append(
            {
                "claim_id": row.id,
                "source_id": row.source_id,
                "entity": row.entity,
                "source_metric": resolution.source_metric,
                "canonical_metric": resolution.canonical_metric,
                "indicator_id": resolution.indicator_id,
                "category": resolution.category,
                "normalization_basis": resolution.basis,
                "value_text": row.value_text,
                "unit": row.unit,
                "expected_units": list(resolution.expected_units),
                "unit_matches_catalog": unit_matches,
                "publication_date": row.publication_date.isoformat() if row.publication_date else None,
                "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                "state": row.state,
                "quality_gate": "pass" if quality_reason is None else "fail",
                "quality_rejection_reason": quality_reason,
                "source_url": row.source_url,
            }
        )

    indicator_rows: list[dict[str, object]] = []
    for definition in definitions:
        claims = by_indicator.get(definition.indicator_id, [])
        latest = max(claims, key=_latest_sort_key) if claims else None
        source_ids = sorted({row.source_id for row in claims})
        observed_units = sorted({row.unit for row in claims if row.unit})
        indicator_rows.append(
            {
                "indicator_id": definition.indicator_id,
                "canonical_metric": definition.canonical_metric,
                "category": definition.category,
                "aliases": list(definition.aliases),
                "expected_units": list(definition.expected_units),
                "description": definition.description,
                "claim_count": len(claims),
                "source_ids": source_ids,
                "observed_units": observed_units,
                "latest_observation": (
                    {
                        "claim_id": latest.id,
                        "source_id": latest.source_id,
                        "source_metric": latest.metric,
                        "entity": latest.entity,
                        "value_text": latest.value_text,
                        "unit": latest.unit,
                        "publication_date": latest.publication_date.isoformat()
                        if latest.publication_date
                        else None,
                        "effective_date": latest.effective_date.isoformat()
                        if latest.effective_date
                        else None,
                        "state": latest.state,
                        "source_url": latest.source_url,
                    }
                    if latest is not None
                    else None
                ),
            }
        )

    mapping_rows.sort(
        key=lambda item: (
            item["indicator_id"] is None,
            str(item["canonical_metric"]).casefold(),
            str(item["source_id"]),
            str(item["claim_id"]),
        )
    )

    unmapped = [
        {"source_metric": metric, "claim_count": count}
        for metric, count in sorted(
            unmapped_counts.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_indicator_catalog_overlay",
        "summary": {
            "catalog_indicators": len(definitions),
            "persisted_claims": len(rows),
            "mapped_claims": mapped_count,
            "unmapped_claims": len(rows) - mapped_count,
            "quality_safe_active_mapped_claims": quality_safe_mapped,
            "observed_indicators": sum(1 for item in indicator_rows if item["claim_count"]),
            "unobserved_indicators": sum(1 for item in indicator_rows if not item["claim_count"]),
        },
        "category_claim_counts": dict(sorted(category_counts.items())),
        "indicators": indicator_rows,
        "claim_mappings": mapping_rows[:limit],
        "unmapped_metrics": unmapped[:limit],
        "safety": {
            "persists_normalization": False,
            "rewrites_source_metric": False,
            "fuzzy_matching_enabled": False,
            "mutates_claim_state": False,
            "enables_trust_promotion": False,
            "note": (
                "Canonical metric labels are an exact-alias read-only overlay. "
                "The original persisted metric remains authoritative evidence metadata."
            ),
        },
    }
