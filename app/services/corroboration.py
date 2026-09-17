from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.claims.eligibility import claim_quality_rejection_reason
from app.sources.registry import get_source_independence_group
from app.storage.database import ClaimRecord, get_session


TERMINAL_STATES = {"rejected", "superseded"}


def _norm(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def _independence_group(source_id: str) -> str:
    try:
        return get_source_independence_group(source_id)
    except ValueError:
        return source_id


def _scope(row: ClaimRecord) -> tuple[str, date] | None:
    if row.effective_date is not None:
        return ("effective", row.effective_date)
    if row.publication_date is not None:
        return ("publication", row.publication_date)
    return None


def _value_key(row: ClaimRecord) -> str:
    if row.value_numeric is not None:
        value = Decimal(row.value_numeric)
        return f"numeric:{value.normalize()}:{_norm(row.unit)}"
    return f"text:{_norm(row.value_text)}"


def _series_key(row: ClaimRecord) -> tuple[str, str, str]:
    return (_norm(row.entity), _norm(row.metric), _norm(row.unit))


def _quality_safe(row: ClaimRecord) -> bool:
    return claim_quality_rejection_reason(row.metric, row.evidence_text) is None


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _peer_summary(row: ClaimRecord) -> dict[str, object]:
    scope = _scope(row)
    return {
        "claim_id": row.id,
        "source_id": row.source_id,
        "independence_group": _independence_group(row.source_id),
        "state": row.state,
        "value_text": row.value_text,
        "unit": row.unit,
        "publication_date": row.publication_date.isoformat() if row.publication_date else None,
        "effective_date": row.effective_date.isoformat() if row.effective_date else None,
        "temporal_scope": (
            {"kind": scope[0], "date": scope[1].isoformat()} if scope is not None else None
        ),
        "source_url": row.source_url,
        "confidence": round(float(row.confidence), 4),
    }


def build_corroboration_snapshot(*, limit: int = 100) -> dict[str, object]:
    """Explain independent-source corroboration coverage without changing state."""
    if not 1 <= limit <= 300:
        raise ValueError("limit must be between 1 and 300")

    with get_session() as session:
        rows = list(session.scalars(select(ClaimRecord)))

    eligible = [
        row
        for row in rows
        if row.state not in TERMINAL_STATES and _quality_safe(row)
    ]
    candidates = [row for row in eligible if row.state == "candidate"]
    diagnostics: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()

    for target in candidates:
        target_group = _independence_group(target.source_id)
        target_scope = _scope(target)
        target_value = _value_key(target)
        peers = [
            row
            for row in eligible
            if row.id != target.id
            and _series_key(row) == _series_key(target)
            and _independence_group(row.source_id) != target_group
        ]

        exact_support = [
            row
            for row in peers
            if target_scope is not None
            and _scope(row) == target_scope
            and _value_key(row) == target_value
        ]
        exact_conflicts = [
            row
            for row in peers
            if target_scope is not None
            and _scope(row) == target_scope
            and _value_key(row) != target_value
        ]
        missing_scope_same_value = [
            row
            for row in peers
            if (_scope(row) is None or target_scope is None)
            and _value_key(row) == target_value
        ]
        different_scope_same_value = [
            row
            for row in peers
            if target_scope is not None
            and _scope(row) is not None
            and _scope(row) != target_scope
            and _value_key(row) == target_value
        ]

        if exact_conflicts:
            reason = "qualifying_independent_conflict_exists"
        elif exact_support:
            reason = "qualifying_independent_support_exists"
        elif missing_scope_same_value or different_scope_same_value:
            reason = "temporal_alignment_missing"
        elif peers:
            reason = "independent_peer_exists_but_not_comparable"
        else:
            reason = "independent_source_coverage_missing"
        reason_counts[reason] += 1

        diagnostics.append(
            {
                "claim_id": target.id,
                "entity": target.entity,
                "metric": target.metric,
                "value_text": target.value_text,
                "unit": target.unit,
                "source_id": target.source_id,
                "independence_group": target_group,
                "publication_date": (
                    target.publication_date.isoformat() if target.publication_date else None
                ),
                "effective_date": (
                    target.effective_date.isoformat() if target.effective_date else None
                ),
                "temporal_scope": (
                    {"kind": target_scope[0], "date": target_scope[1].isoformat()}
                    if target_scope is not None
                    else None
                ),
                "diagnostic_reason": reason,
                "independent_peer_count": len(peers),
                "exact_support": [_peer_summary(row) for row in exact_support],
                "exact_conflicts": [_peer_summary(row) for row in exact_conflicts],
                "same_value_missing_scope": [
                    _peer_summary(row) for row in missing_scope_same_value
                ],
                "same_value_different_scope": [
                    _peer_summary(row) for row in different_scope_same_value
                ],
                "source_url": target.source_url,
                "evidence_excerpt": " ".join((target.evidence_text or "").split())[:320],
                "created_at": _iso(target.created_at),
            }
        )

    priority = {
        "qualifying_independent_conflict_exists": 0,
        "qualifying_independent_support_exists": 1,
        "temporal_alignment_missing": 2,
        "independent_peer_exists_but_not_comparable": 3,
        "independent_source_coverage_missing": 4,
    }
    diagnostics.sort(
        key=lambda item: (
            priority.get(str(item["diagnostic_reason"]), 99),
            str(item["entity"]),
            str(item["metric"]),
            str(item["claim_id"]),
        )
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_corroboration_diagnostics",
        "summary": {
            "total_claims": len(rows),
            "quality_safe_nonterminal_claims": len(eligible),
            "candidate_claims": len(candidates),
            "diagnostics_returned": min(len(diagnostics), limit),
        },
        "reason_counts": dict(sorted(reason_counts.items())),
        "items": diagnostics[:limit],
        "safety": {
            "mutates_claim_state": False,
            "creates_verification_events": False,
            "promotes_trust": False,
            "note": (
                "Diagnostics only identify why candidate evidence is or is not comparable. "
                "They do not relax entity, metric, unit, temporal-scope, value, quality, "
                "or publisher-independence requirements."
            ),
        },
    }
