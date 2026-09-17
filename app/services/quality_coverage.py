from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from typing import Iterable

from sqlalchemy import select

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.sources.registry import get_source_independence_group
from app.storage.database import ClaimEntityAttributionRecord, ClaimRecord, get_session


def _norm(value: object | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip().lower()


def _independence_group(source_id: str) -> str:
    try:
        return get_source_independence_group(source_id)
    except ValueError:
        return source_id


def _temporal_scope(row: ClaimRecord) -> tuple[str, date] | None:
    if row.effective_date is not None:
        return ("effective", row.effective_date)
    if row.publication_date is not None:
        return ("publication", row.publication_date)
    return None


def _value_key(row: ClaimRecord) -> str:
    if row.value_numeric is not None:
        return f"numeric:{_norm(row.value_numeric)}:{_norm(row.unit)}"
    return f"text:{_norm(row.value_text)}"


def _active(rows: Iterable[ClaimRecord]) -> list[ClaimRecord]:
    terminal = {ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value}
    return [row for row in rows if row.state not in terminal]


def build_quality_coverage_snapshot(*, limit: int = 100) -> dict[str, object]:
    """Explain extraction quality and cross-source verification coverage read-only.

    The report never mutates claims or source evidence. It inventories known
    quality blockers and groups quality-safe active claims by the exact comparison
    dimensions used by verification: entity, metric, unit, and persisted temporal
    scope. Independence groups are respected so sibling publishers do not count as
    separate corroboration.
    """
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    with get_session() as session:
        rows = list(session.scalars(select(ClaimRecord)))
        attributions = list(session.scalars(select(ClaimEntityAttributionRecord)))

    active_rows = _active(rows)
    attribution_by_claim = {row.claim_id: row for row in attributions}

    quality_reason_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter(row.state for row in rows)
    source_stats: dict[str, Counter[str]] = defaultdict(Counter)
    attribution_basis_counts: Counter[str] = Counter()
    quality_safe_active: list[ClaimRecord] = []
    missing_temporal: list[ClaimRecord] = []

    for row in rows:
        source_stats[row.source_id]["claims_total"] += 1
        if row.state not in {ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value}:
            source_stats[row.source_id]["claims_active"] += 1

        attribution = attribution_by_claim.get(row.id)
        basis = attribution.basis if attribution is not None else "unspecified"
        attribution_basis_counts[basis] += 1
        source_stats[row.source_id][f"attribution_{basis}"] += 1

        reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        if reason is not None:
            quality_reason_counts[reason] += 1
            source_stats[row.source_id]["quality_failed"] += 1
            continue

        source_stats[row.source_id]["quality_passed"] += 1
        if row.state in {ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value}:
            continue

        quality_safe_active.append(row)
        if _temporal_scope(row) is None:
            missing_temporal.append(row)
            source_stats[row.source_id]["missing_temporal_scope"] += 1

    grouped: dict[
        tuple[str, str, str, tuple[str, date]],
        list[ClaimRecord],
    ] = defaultdict(list)
    for row in quality_safe_active:
        scope = _temporal_scope(row)
        if scope is None:
            continue
        key = (_norm(row.entity), _norm(row.metric), _norm(row.unit), scope)
        grouped[key].append(row)

    coverage_counts: Counter[str] = Counter()
    coverage_groups: list[dict[str, object]] = []

    for (_entity, _metric, _unit, scope), members in grouped.items():
        sources = sorted({row.source_id for row in members})
        independence_groups = sorted({_independence_group(row.source_id) for row in members})
        by_value_groups: dict[str, set[str]] = defaultdict(set)
        by_value_sources: dict[str, set[str]] = defaultdict(set)
        for row in members:
            value_key = _value_key(row)
            group = _independence_group(row.source_id)
            by_value_groups[value_key].add(group)
            by_value_sources[value_key].add(row.source_id)

        if len(independence_groups) < 2:
            status = "single_independence_group"
        elif len(by_value_groups) == 1:
            status = "independently_supported_same_value"
        else:
            status = "independent_values_disagree"

        coverage_counts[status] += 1
        first = members[0]
        values = [
            {
                "value": key,
                "source_ids": sorted(by_value_sources[key]),
                "independence_groups": sorted(groups),
            }
            for key, groups in sorted(by_value_groups.items())
        ]
        coverage_groups.append(
            {
                "entity": first.entity,
                "metric": first.metric,
                "unit": first.unit,
                "temporal_kind": scope[0],
                "temporal_date": scope[1].isoformat(),
                "claim_count": len(members),
                "source_ids": sources,
                "independence_groups": independence_groups,
                "independence_group_count": len(independence_groups),
                "distinct_values": len(values),
                "coverage_status": status,
                "values": values,
            }
        )

    status_priority = {
        "independent_values_disagree": 0,
        "single_independence_group": 1,
        "independently_supported_same_value": 2,
    }
    coverage_groups.sort(
        key=lambda item: (
            status_priority.get(str(item["coverage_status"]), 99),
            str(item["entity"]).lower(),
            str(item["metric"]).lower(),
            str(item["temporal_date"]),
        )
    )

    missing_temporal_items = [
        {
            "claim_id": row.id,
            "source_id": row.source_id,
            "entity": row.entity,
            "metric": row.metric,
            "value_text": row.value_text,
            "unit": row.unit,
            "state": row.state,
            "evidence_excerpt": " ".join((row.evidence_text or "").split())[:280],
            "source_url": row.source_url,
        }
        for row in sorted(
            missing_temporal,
            key=lambda row: (row.source_id, _norm(row.entity), _norm(row.metric), row.id),
        )[:limit]
    ]

    per_source = []
    for source_id, counts in sorted(source_stats.items()):
        per_source.append(
            {
                "source_id": source_id,
                "claims_total": counts["claims_total"],
                "claims_active": counts["claims_active"],
                "quality_passed": counts["quality_passed"],
                "quality_failed": counts["quality_failed"],
                "missing_temporal_scope": counts["missing_temporal_scope"],
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_quality_verification_coverage",
        "summary": {
            "claims_total": len(rows),
            "claims_active": len(active_rows),
            "quality_safe_active_claims": len(quality_safe_active),
            "quality_failed_claims": sum(quality_reason_counts.values()),
            "missing_temporal_scope": len(missing_temporal),
            "comparison_groups": len(coverage_groups),
            "single_independence_group_groups": coverage_counts[
                "single_independence_group"
            ],
            "independently_supported_groups": coverage_counts[
                "independently_supported_same_value"
            ],
            "independent_conflict_groups": coverage_counts[
                "independent_values_disagree"
            ],
        },
        "state_counts": dict(sorted(state_counts.items())),
        "quality_reason_counts": dict(sorted(quality_reason_counts.items())),
        "attribution_basis_counts": dict(sorted(attribution_basis_counts.items())),
        "per_source": per_source,
        "coverage_status_counts": dict(sorted(coverage_counts.items())),
        "coverage_groups": coverage_groups[:limit],
        "missing_temporal_items": missing_temporal_items,
        "safety": {
            "mutates_claims": False,
            "mutates_evidence": False,
            "creates_verification_events": False,
            "enables_trust_promotion": False,
            "note": (
                "Coverage groups are diagnostics only. They do not change claim state or "
                "treat a group as verified/trusted outside the existing lifecycle policy."
            ),
        },
    }
