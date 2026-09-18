from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.claims.catalog import normalize_indicator_metric
from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState
from app.sources.registry import get_source, get_source_independence_group
from app.storage.database import ClaimRecord, DocumentRecord, get_session

MAX_SCANNED_CLAIMS = 20_000


def _norm(value: object | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip().casefold()


def _source_meta(source_id: str) -> dict[str, object]:
    try:
        source = get_source(source_id)
        group = get_source_independence_group(source_id)
        return {
            "source_name": source.name,
            "authority_level": source.authority_level.value,
            "independence_group": group,
        }
    except ValueError:
        return {
            "source_name": source_id,
            "authority_level": None,
            "independence_group": source_id,
        }


def _temporal_scope(row: ClaimRecord) -> tuple[str, date] | None:
    if row.effective_date is not None:
        return ("effective_date", row.effective_date)
    if row.publication_date is not None:
        return ("publication_date", row.publication_date)
    return None


def _comparison_metric(row: ClaimRecord) -> tuple[str, str, str | None, str]:
    resolution = normalize_indicator_metric(row.metric)
    if resolution.indicator_id is not None:
        return (
            f"indicator:{resolution.indicator_id}",
            resolution.canonical_metric,
            resolution.indicator_id,
            resolution.basis,
        )
    return (
        f"source_metric:{_norm(row.metric)}",
        row.metric,
        None,
        resolution.basis,
    )


def _value_key(row: ClaimRecord) -> tuple[str, str]:
    if row.value_numeric is not None:
        return ("numeric", _norm(row.value_numeric))
    return ("text", _norm(row.value_text))


def build_conflict_investigation_snapshot(
    *,
    participant_source_id: str | None = None,
    entity_contains: str | None = None,
    metric_contains: str | None = None,
    limit: int = 50,
) -> dict[str, object]:
    """Return independently sourced exact-comparison disagreements read-only.

    Claims are comparable only when entity, deterministic metric identity, unit,
    and persisted temporal scope match. A conflict is surfaced only when at least
    two publisher-independence groups participate and more than one value exists.
    The function never resolves which value is true and never changes claim state.
    """
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    participant_source_id = (participant_source_id or "").strip() or None
    entity_contains = (entity_contains or "").strip() or None
    metric_contains = (metric_contains or "").strip() or None

    terminal_states = {ClaimState.REJECTED.value, ClaimState.SUPERSEDED.value}
    with get_session() as session:
        rows = list(
            session.scalars(
                select(ClaimRecord)
                .where(ClaimRecord.state.not_in(terminal_states))
                .order_by(ClaimRecord.created_at.asc(), ClaimRecord.id.asc())
                .limit(MAX_SCANNED_CLAIMS + 1)
            )
        )
        if len(rows) > MAX_SCANNED_CLAIMS:
            raise ValueError(
                "active claim scan exceeds the safety bound; narrow the investigation scope"
            )

        document_ids = sorted({row.document_id for row in rows})
        documents = (
            list(
                session.scalars(
                    select(DocumentRecord).where(DocumentRecord.id.in_(document_ids))
                )
            )
            if document_ids
            else []
        )

    docs_by_id = {row.id: row for row in documents}
    excluded_counts: Counter[str] = Counter()
    groups: dict[tuple[str, str, str, str, date], list[ClaimRecord]] = defaultdict(list)

    for row in rows:
        if entity_contains and entity_contains.casefold() not in row.entity.casefold():
            continue
        if metric_contains and metric_contains.casefold() not in row.metric.casefold():
            continue

        quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        if quality_reason is not None:
            excluded_counts["quality_failed"] += 1
            continue

        scope = _temporal_scope(row)
        if scope is None:
            excluded_counts["missing_temporal_scope"] += 1
            continue

        metric_key, _canonical_metric, _indicator_id, _basis = _comparison_metric(row)
        groups[
            (
                _norm(row.entity),
                metric_key,
                _norm(row.unit),
                scope[0],
                scope[1],
            )
        ].append(row)

    investigated_groups = 0
    conflict_groups: list[dict[str, object]] = []
    agreement_groups = 0
    single_publisher_groups = 0

    for (_entity_key, _metric_key, _unit_key, temporal_kind, temporal_date), members in groups.items():
        source_meta = {row.source_id: _source_meta(row.source_id) for row in members}
        independence_groups = sorted(
            {str(source_meta[row.source_id]["independence_group"]) for row in members}
        )
        if participant_source_id is not None and participant_source_id not in {
            row.source_id for row in members
        }:
            continue

        investigated_groups += 1
        if len(independence_groups) < 2:
            single_publisher_groups += 1
            continue

        by_value: dict[tuple[str, str], list[ClaimRecord]] = defaultdict(list)
        for row in members:
            by_value[_value_key(row)].append(row)

        if len(by_value) == 1:
            agreement_groups += 1
            continue

        first = members[0]
        _comparison_key, canonical_metric, indicator_id, normalization_basis = _comparison_metric(first)
        value_groups: list[dict[str, object]] = []
        for (_value_kind, _normalized_value), value_members in sorted(
            by_value.items(), key=lambda item: item[0]
        ):
            value_groups.append(
                {
                    "display_value": value_members[0].value_text,
                    "value_numeric": (
                        str(value_members[0].value_numeric)
                        if value_members[0].value_numeric is not None
                        else None
                    ),
                    "unit": value_members[0].unit,
                    "source_ids": sorted({row.source_id for row in value_members}),
                    "independence_groups": sorted(
                        {
                            str(source_meta[row.source_id]["independence_group"])
                            for row in value_members
                        }
                    ),
                    "claims": [
                        {
                            "claim_id": row.id,
                            "document_id": row.document_id,
                            "source_id": row.source_id,
                            **source_meta[row.source_id],
                            "state": row.state,
                            "confidence": round(float(row.confidence), 4),
                            "publication_date": (
                                row.publication_date.isoformat() if row.publication_date else None
                            ),
                            "effective_date": (
                                row.effective_date.isoformat() if row.effective_date else None
                            ),
                            "source_url": row.source_url,
                            "evidence_excerpt": " ".join((row.evidence_text or "").split())[:500],
                            "document": (
                                {
                                    "title": docs_by_id[row.document_id].title,
                                    "sha256": docs_by_id[row.document_id].sha256,
                                    "retrieved_at": docs_by_id[row.document_id].retrieved_at.astimezone(
                                        UTC
                                    ).isoformat()
                                    if docs_by_id[row.document_id].retrieved_at.tzinfo
                                    else docs_by_id[row.document_id]
                                    .retrieved_at.replace(tzinfo=UTC)
                                    .isoformat(),
                                    "status": docs_by_id[row.document_id].status,
                                }
                                if row.document_id in docs_by_id
                                else None
                            ),
                        }
                        for row in sorted(
                            value_members,
                            key=lambda item: (item.source_id, item.document_id, item.id),
                        )
                    ],
                }
            )

        conflict_groups.append(
            {
                "entity": first.entity,
                "source_metric": first.metric,
                "canonical_metric": canonical_metric,
                "indicator_id": indicator_id,
                "normalization_basis": normalization_basis,
                "unit": first.unit,
                "temporal_kind": temporal_kind,
                "temporal_date": temporal_date.isoformat(),
                "claim_count": len(members),
                "source_ids": sorted({row.source_id for row in members}),
                "independence_groups": independence_groups,
                "distinct_values": len(value_groups),
                "values": value_groups,
                "interpretation": (
                    "Independent persisted sources contain different values for the same exact "
                    "comparison scope. This view does not choose a winning value."
                ),
            }
        )

    conflict_groups.sort(
        key=lambda item: (
            str(item["temporal_date"]),
            str(item["entity"]).casefold(),
            str(item["canonical_metric"]).casefold(),
        ),
        reverse=True,
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_conflict_investigation",
        "scope": {
            "participant_source_id": participant_source_id,
            "entity_contains": entity_contains,
            "metric_contains": metric_contains,
            "limit": limit,
        },
        "summary": {
            "active_claims_scanned": len(rows),
            "comparison_groups_in_scope": investigated_groups,
            "independent_conflict_groups": len(conflict_groups),
            "independent_agreement_groups": agreement_groups,
            "single_independence_group_groups": single_publisher_groups,
            "quality_failed_excluded": excluded_counts["quality_failed"],
            "missing_temporal_scope_excluded": excluded_counts["missing_temporal_scope"],
            "returned_conflict_groups": min(len(conflict_groups), limit),
        },
        "conflicts": conflict_groups[:limit],
        "comparison_contract": {
            "entity": "exact_normalized",
            "metric": "exact_catalog_alias_else_exact_normalized_source_metric",
            "unit": "exact_normalized",
            "temporal_scope": "effective_date_else_publication_date_with_kind_preserved",
            "publisher_independence": True,
            "quality_failed_claims_excluded": True,
            "missing_dates_excluded_from_comparison": True,
        },
        "safety": {
            "read_only": True,
            "mutates_claim_state": False,
            "creates_verification_events": False,
            "creates_trust_events": False,
            "resolves_conflicts_automatically": False,
            "fuzzy_matching": False,
            "invented_dates": False,
            "network_crawling": False,
            "note": (
                "A displayed conflict is a factual disagreement among independently published "
                "persisted claims in one exact comparison scope. No source is declared correct."
            ),
        },
    }
