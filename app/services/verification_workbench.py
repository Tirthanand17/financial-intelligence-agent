from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState, StructuredClaim
from app.claims.verification import assess_claim
from app.sources.registry import get_source
from app.storage.database import ClaimRecord, ClaimVerificationEventRecord, get_session


def _to_structured(row: ClaimRecord) -> StructuredClaim | None:
    try:
        state = ClaimState(row.state)
    except ValueError:
        return None
    return StructuredClaim(
        entity=row.entity,
        metric=row.metric,
        value_text=row.value_text,
        value_numeric=Decimal(row.value_numeric) if row.value_numeric is not None else None,
        unit=row.unit,
        publication_date=row.publication_date,
        effective_date=row.effective_date,
        source_id=row.source_id,
        source_url=row.source_url,
        document_id=row.document_id,
        evidence_text=row.evidence_text,
        evidence_chunk_index=row.evidence_chunk_index,
        confidence=float(row.confidence),
        state=state,
    )


def _source_meta(source_id: str) -> dict[str, object]:
    try:
        source = get_source(source_id)
        return {
            "source_name": source.name,
            "authority_level": source.authority_level.value,
            "independence_group": source.independence_group or source.source_id,
        }
    except ValueError:
        return {
            "source_name": source_id,
            "authority_level": None,
            "independence_group": source_id,
        }


def build_verification_workbench(*, limit: int = 50) -> dict[str, object]:
    """Explain current verification readiness without changing claim state."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")

    with get_session() as session:
        rows = list(session.scalars(select(ClaimRecord)))
        events = list(session.scalars(select(ClaimVerificationEventRecord)))

    structured_pairs: list[tuple[ClaimRecord, StructuredClaim]] = []
    invalid_state_ids: list[str] = []
    for row in rows:
        claim = _to_structured(row)
        if claim is None:
            invalid_state_ids.append(row.id)
            continue
        structured_pairs.append((row, claim))

    evidence = [claim for _row, claim in structured_pairs]
    latest_event_by_claim: dict[str, ClaimVerificationEventRecord] = {}
    for event in sorted(events, key=lambda item: item.created_at):
        latest_event_by_claim[event.claim_id] = event

    reason_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter(row.state for row in rows)
    items: list[dict[str, object]] = []

    for row, claim in structured_pairs:
        quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        decision = assess_claim(claim, evidence)
        reason_counts[decision.reason] += 1
        source_meta = _source_meta(row.source_id)
        latest_event = latest_event_by_claim.get(row.id)

        items.append(
            {
                "claim_id": row.id,
                "current_state": row.state,
                "recommended_state": decision.state.value,
                "verification_reason": decision.reason,
                "quality_gate": "pass" if quality_reason is None else "fail",
                "quality_rejection_reason": quality_reason,
                "source_id": row.source_id,
                **source_meta,
                "entity": row.entity,
                "metric": row.metric,
                "value_text": row.value_text,
                "unit": row.unit,
                "publication_date": row.publication_date.isoformat() if row.publication_date else None,
                "effective_date": row.effective_date.isoformat() if row.effective_date else None,
                "confidence": round(float(row.confidence), 4),
                "supporting_source_ids": list(decision.supporting_source_ids),
                "conflicting_source_ids": list(decision.conflicting_source_ids),
                "source_url": row.source_url,
                "evidence_excerpt": " ".join((row.evidence_text or "").split())[:320],
                "latest_verification_event": (
                    {
                        "from_state": latest_event.from_state,
                        "to_state": latest_event.to_state,
                        "reason": latest_event.reason,
                        "supporting_source_ids": latest_event.supporting_source_ids,
                        "conflicting_source_ids": latest_event.conflicting_source_ids,
                        "created_at": (
                            latest_event.created_at.replace(tzinfo=UTC).isoformat()
                            if latest_event.created_at.tzinfo is None
                            else latest_event.created_at.astimezone(UTC).isoformat()
                        ),
                    }
                    if latest_event is not None
                    else None
                ),
            }
        )

    priority = {
        "independent_sources_disagree": 0,
        "quality_gate_failed": 1,
        "missing_temporal_scope": 2,
        "insufficient_independent_sources": 3,
        "independent_sources_agree": 4,
        "terminal_state_preserved": 5,
    }
    items.sort(
        key=lambda item: (
            priority.get(str(item["verification_reason"]), 99),
            -float(item["confidence"]),
            str(item["claim_id"]),
        )
    )

    actionable = [
        item
        for item in items
        if item["verification_reason"]
        in {
            "independent_sources_disagree",
            "quality_gate_failed",
            "missing_temporal_scope",
            "insufficient_independent_sources",
        }
    ]
    ready_to_verify = [
        item for item in items if item["verification_reason"] == "independent_sources_agree"
    ]

    source_reason_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        source_reason_counts[str(item["source_id"])][str(item["verification_reason"])] += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_verification_workbench",
        "summary": {
            "total_claims": len(rows),
            "valid_modeled_claims": len(structured_pairs),
            "invalid_state_claims": len(invalid_state_ids),
            "actionable_review_items": len(actionable),
            "ready_for_verification": len(ready_to_verify),
            "verification_events": len(events),
        },
        "state_counts": dict(sorted(state_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "source_reason_counts": {
            source_id: dict(sorted(counts.items()))
            for source_id, counts in sorted(source_reason_counts.items())
        },
        "invalid_state_claim_ids": sorted(invalid_state_ids),
        "items": items[:limit],
        "safety": {
            "mutates_claim_state": False,
            "trust_promotion_enabled_by_workbench": False,
            "note": (
                "Recommended state is an explanation of current persisted evidence only. "
                "This workbench never writes a claim transition or trust event."
            ),
        },
    }
