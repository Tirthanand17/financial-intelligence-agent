from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState, StructuredClaim
from app.claims.trust import assess_trust
from app.claims.verification import assess_claim
from app.sources.registry import get_source, get_source_independence_group
from app.storage.database import (
    ClaimEntityAttributionRecord,
    ClaimRecord,
    ClaimSupersessionRecord,
    ClaimTrustEventRecord,
    ClaimVerificationEventRecord,
    get_session,
)


ACTIONABLE_REASONS = {
    "independent_sources_disagree",
    "quality_gate_failed",
    "missing_temporal_scope",
    "insufficient_independent_sources",
}


def _decode_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _dt_key(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _source_meta(source_id: str) -> dict[str, object]:
    try:
        source = get_source(source_id)
        return {
            "source_name": source.name,
            "authority_level": source.authority_level.value,
            "category": source.category,
            "independence_group": source.independence_group or source.source_id,
        }
    except ValueError:
        return {
            "source_name": source_id,
            "authority_level": None,
            "category": None,
            "independence_group": source_id,
        }


def _independence_group(source_id: str) -> str:
    try:
        return get_source_independence_group(source_id)
    except ValueError:
        return source_id


def _to_structured(
    row: ClaimRecord,
    attribution: ClaimEntityAttributionRecord | None,
) -> StructuredClaim | None:
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
        entity_attribution_basis=(attribution.basis if attribution is not None else "unspecified"),
        entity_source_default=(
            attribution.source_default_entity if attribution is not None else None
        ),
        entity_matched_aliases=tuple(
            _decode_list(attribution.matched_aliases) if attribution is not None else []
        ),
        entity_ambiguous_candidates=tuple(
            _decode_list(attribution.ambiguous_candidates)
            if attribution is not None
            else []
        ),
        entity_evidence_text=(attribution.evidence_text if attribution is not None else None),
        confidence=float(row.confidence),
        state=state,
    )


def _latest_event_map(events: list[object]) -> dict[str, object]:
    latest: dict[str, object] = {}
    for event in sorted(events, key=lambda item: _dt_key(getattr(item, "created_at", None))):
        latest[str(getattr(event, "claim_id"))] = event
    return latest


def build_verification_workbench(
    *,
    source_id: str | None = None,
    state: str | None = None,
    limit: int = 50,
) -> dict[str, object]:
    """Explain claim verification/trust readiness without mutating persisted state.

    The workbench intentionally evaluates the same pure verification and trust
    policies used by the persistence layer, but it never writes a transition,
    trust event, supersession event, attribution, or source record.
    """
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")

    valid_states = {member.value for member in ClaimState}
    if state is not None and state not in valid_states:
        raise ValueError(f"unknown claim state: {state}")

    with get_session() as session:
        rows = list(session.scalars(select(ClaimRecord)))
        attributions = list(session.scalars(select(ClaimEntityAttributionRecord)))
        verification_events = list(session.scalars(select(ClaimVerificationEventRecord)))
        trust_events = list(session.scalars(select(ClaimTrustEventRecord)))
        supersessions = list(session.scalars(select(ClaimSupersessionRecord)))

    attribution_by_claim = {row.claim_id: row for row in attributions}
    latest_verification = _latest_event_map(verification_events)
    latest_trust = _latest_event_map(trust_events)
    supersession_by_older = {row.older_claim_id: row for row in supersessions}
    superseded_by_newer: dict[str, list[ClaimSupersessionRecord]] = defaultdict(list)
    for row in supersessions:
        superseded_by_newer[row.newer_claim_id].append(row)

    structured_pairs: list[tuple[ClaimRecord, StructuredClaim]] = []
    invalid_state_ids: list[str] = []
    for row in rows:
        claim = _to_structured(row, attribution_by_claim.get(row.id))
        if claim is None:
            invalid_state_ids.append(row.id)
            continue
        structured_pairs.append((row, claim))

    evidence = [claim for _row, claim in structured_pairs]
    all_items: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    for row, claim in structured_pairs:
        quality_reason = claim_quality_rejection_reason(row.metric, row.evidence_text)
        verification = assess_claim(claim, evidence)
        trust = assess_trust(claim, evidence)

        reconciled_state = verification.state
        if claim.state is ClaimState.TRUSTED and verification.state is not ClaimState.CONFLICTED:
            reconciled_state = ClaimState.TRUSTED

        source_meta = _source_meta(row.source_id)
        supporting_groups = sorted({_independence_group(sid) for sid in verification.supporting_source_ids})
        conflicting_groups = sorted({_independence_group(sid) for sid in verification.conflicting_source_ids})
        verification_event = latest_verification.get(row.id)
        trust_event = latest_trust.get(row.id)
        attribution = attribution_by_claim.get(row.id)
        superseded = supersession_by_older.get(row.id)
        supersedes = sorted(
            superseded_by_newer.get(row.id, []),
            key=lambda item: (item.older_date, item.older_claim_id),
        )

        reason_counts[verification.reason] += 1
        source_counts[row.source_id] += 1

        all_items.append(
            {
                "claim_id": row.id,
                "current_state": row.state,
                "evidence_assessed_state": verification.state.value,
                "safe_reconciled_state": reconciled_state.value,
                "verification_reason": verification.reason,
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
                "supporting_source_ids": list(verification.supporting_source_ids),
                "supporting_independence_groups": supporting_groups,
                "conflicting_source_ids": list(verification.conflicting_source_ids),
                "conflicting_independence_groups": conflicting_groups,
                "trust_diagnostic": {
                    "assessed_state": trust.state.value,
                    "reason": trust.reason,
                    "corroborating_source_ids": list(trust.corroborating_source_ids),
                    "policy_eligible_without_mutation": (
                        claim.state is ClaimState.VERIFIED
                        and trust.state is ClaimState.TRUSTED
                    ),
                },
                "entity_attribution": {
                    "basis": attribution.basis if attribution is not None else "unspecified",
                    "source_default_entity": (
                        attribution.source_default_entity if attribution is not None else None
                    ),
                    "matched_aliases": (
                        _decode_list(attribution.matched_aliases)
                        if attribution is not None
                        else []
                    ),
                    "ambiguous_candidates": (
                        _decode_list(attribution.ambiguous_candidates)
                        if attribution is not None
                        else []
                    ),
                },
                "latest_verification_event": (
                    {
                        "from_state": verification_event.from_state,
                        "to_state": verification_event.to_state,
                        "reason": verification_event.reason,
                        "supporting_source_ids": _decode_list(
                            verification_event.supporting_source_ids
                        ),
                        "conflicting_source_ids": _decode_list(
                            verification_event.conflicting_source_ids
                        ),
                        "created_at": _utc_iso(verification_event.created_at),
                    }
                    if verification_event is not None
                    else None
                ),
                "latest_trust_event": (
                    {
                        "from_state": trust_event.from_state,
                        "to_state": trust_event.to_state,
                        "reason": trust_event.reason,
                        "corroborating_source_ids": _decode_list(
                            trust_event.corroborating_source_ids
                        ),
                        "created_at": _utc_iso(trust_event.created_at),
                    }
                    if trust_event is not None
                    else None
                ),
                "supersession": (
                    {
                        "superseded_by_claim_id": superseded.newer_claim_id,
                        "newer_document_id": superseded.newer_document_id,
                        "temporal_kind": superseded.temporal_kind,
                        "older_date": superseded.older_date.isoformat(),
                        "newer_date": superseded.newer_date.isoformat(),
                    }
                    if superseded is not None
                    else None
                ),
                "supersedes_claim_ids": [item.older_claim_id for item in supersedes],
                "source_url": row.source_url,
                "evidence_excerpt": " ".join((row.evidence_text or "").split())[:360],
                "created_at": _utc_iso(row.created_at),
                "updated_at": _utc_iso(row.updated_at),
            }
        )

    scoped = [
        item
        for item in all_items
        if (source_id is None or item["source_id"] == source_id)
        and (state is None or item["current_state"] == state)
    ]

    priority = {
        "independent_sources_disagree": 0,
        "quality_gate_failed": 1,
        "missing_temporal_scope": 2,
        "insufficient_independent_sources": 3,
        "independent_sources_agree": 4,
        "terminal_state_preserved": 5,
    }
    scoped.sort(
        key=lambda item: (
            priority.get(str(item["verification_reason"]), 99),
            -float(item["confidence"]),
            str(item["claim_id"]),
        )
    )

    scoped_ids = {str(item["claim_id"]) for item in scoped}
    actionable = [item for item in scoped if item["verification_reason"] in ACTIONABLE_REASONS]
    ready_to_verify = [
        item
        for item in scoped
        if item["safe_reconciled_state"] == ClaimState.VERIFIED.value
        and item["current_state"] not in {ClaimState.VERIFIED.value, ClaimState.TRUSTED.value}
    ]
    trust_policy_eligible = [
        item
        for item in scoped
        if bool(item["trust_diagnostic"]["policy_eligible_without_mutation"])
    ]
    conflicts = [item for item in scoped if item["verification_reason"] == "independent_sources_disagree"]
    quality_blocked = [item for item in scoped if item["quality_gate"] == "fail"]

    scoped_reason_counts = Counter(str(item["verification_reason"]) for item in scoped)
    scoped_state_counts = Counter(str(item["current_state"]) for item in scoped)
    source_reason_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in scoped:
        source_reason_counts[str(item["source_id"])][str(item["verification_reason"])] += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only_verification_workbench",
        "scope": {"source_id": source_id, "state": state, "limit": limit},
        "summary": {
            "total_claims_in_scope": len(scoped),
            "valid_modeled_claims_total": len(structured_pairs),
            "invalid_state_claims_total": len(invalid_state_ids),
            "actionable_review_items": len(actionable),
            "ready_for_verification": len(ready_to_verify),
            "trust_policy_eligible": len(trust_policy_eligible),
            "conflicted_claims": len(conflicts),
            "quality_blocked_claims": len(quality_blocked),
            "verification_events_in_scope": sum(
                1 for event in verification_events if event.claim_id in scoped_ids
            ),
            "trust_events_in_scope": sum(
                1 for event in trust_events if event.claim_id in scoped_ids
            ),
            "supersession_links_in_scope": sum(
                1
                for relation in supersessions
                if relation.older_claim_id in scoped_ids or relation.newer_claim_id in scoped_ids
            ),
        },
        "state_counts": dict(sorted(scoped_state_counts.items())),
        "reason_counts": dict(sorted(scoped_reason_counts.items())),
        "available_sources": [
            {"source_id": sid, "claims": count, **_source_meta(sid)}
            for sid, count in sorted(source_counts.items())
        ],
        "source_reason_counts": {
            current_source: dict(sorted(counts.items()))
            for current_source, counts in sorted(source_reason_counts.items())
        },
        "invalid_state_claim_ids": sorted(invalid_state_ids),
        "items": scoped[:limit],
        "safety": {
            "mutates_claim_state": False,
            "creates_verification_events": False,
            "creates_trust_events": False,
            "trust_promotion_enabled_by_workbench": False,
            "note": (
                "All verification and trust results are diagnostics over persisted evidence. "
                "This workbench is read-only and cannot promote trust, resolve conflicts, "
                "change claim state, or alter evidence history."
            ),
        },
    }
