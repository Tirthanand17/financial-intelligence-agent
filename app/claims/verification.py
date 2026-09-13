from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState, StructuredClaim
from app.sources.registry import get_source_independence_group


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    """Result of evaluating one claim against comparable evidence."""

    state: ClaimState
    reason: str
    supporting_source_ids: tuple[str, ...] = ()
    conflicting_source_ids: tuple[str, ...] = ()


def _normalized_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def _temporal_scope(claim: StructuredClaim) -> tuple[str, date] | None:
    if claim.effective_date is not None:
        return ("effective", claim.effective_date)
    if claim.publication_date is not None:
        return ("publication", claim.publication_date)
    return None


def _comparison_key(claim: StructuredClaim) -> tuple[str, str, str, tuple[str, date]] | None:
    scope = _temporal_scope(claim)
    if scope is None:
        return None
    return (
        _normalized_text(claim.entity),
        _normalized_text(claim.metric),
        _normalized_text(claim.unit),
        scope,
    )


def _value_key(claim: StructuredClaim) -> str:
    if claim.value_numeric is not None:
        return (
            f"numeric:{claim.value_numeric.normalize()}:"
            f"{_normalized_text(claim.unit)}"
        )
    return f"text:{_normalized_text(claim.value_text)}"


def _independence_group(source_id: str) -> str:
    try:
        return get_source_independence_group(source_id)
    except ValueError:
        return source_id


def _quality_ok(claim: StructuredClaim) -> bool:
    return claim_quality_rejection_reason(claim.metric, claim.evidence_text) is None


def assess_claim(
    target: StructuredClaim,
    evidence: list[StructuredClaim],
) -> VerificationDecision:
    """Assess one claim without mutating it or writing to the database.

    Verification requires independent groups to agree on the same entity, metric,
    unit, value and temporal scope. Phase 16 additionally prevents legacy parser
    noise from serving as either a verification target or corroborating evidence.
    A quality-failed legacy target is preserved in its current state for explicit
    review rather than being silently rewritten.
    """
    if target.state in {ClaimState.REJECTED, ClaimState.SUPERSEDED}:
        return VerificationDecision(
            state=target.state,
            reason="terminal_state_preserved",
        )

    if not _quality_ok(target):
        return VerificationDecision(
            state=target.state,
            reason="quality_gate_failed",
            supporting_source_ids=(target.source_id,),
        )

    target_key = _comparison_key(target)
    if target_key is None:
        return VerificationDecision(
            state=ClaimState.CANDIDATE,
            reason="missing_temporal_scope",
            supporting_source_ids=(target.source_id,),
        )

    comparable = [
        claim
        for claim in evidence
        if _quality_ok(claim) and _comparison_key(claim) == target_key
    ]
    if not any(claim is target for claim in comparable):
        comparable.append(target)

    by_value_sources: dict[str, set[str]] = defaultdict(set)
    by_value_groups: dict[str, set[str]] = defaultdict(set)
    source_groups: dict[str, str] = {}

    for claim in comparable:
        if claim.state in {ClaimState.REJECTED, ClaimState.SUPERSEDED}:
            continue
        value = _value_key(claim)
        group = _independence_group(claim.source_id)
        by_value_sources[value].add(claim.source_id)
        by_value_groups[value].add(group)
        source_groups[claim.source_id] = group

    target_value = _value_key(target)
    target_group = _independence_group(target.source_id)
    supporting_sources = tuple(
        sorted(by_value_sources.get(target_value, {target.source_id}))
    )

    conflicting_sources = tuple(
        sorted(
            {
                source_id
                for value, source_ids in by_value_sources.items()
                if value != target_value
                for source_id in source_ids
                if source_groups.get(source_id, _independence_group(source_id))
                != target_group
            }
        )
    )

    if conflicting_sources:
        return VerificationDecision(
            state=ClaimState.CONFLICTED,
            reason="independent_sources_disagree",
            supporting_source_ids=supporting_sources,
            conflicting_source_ids=conflicting_sources,
        )

    independent_support = len(by_value_groups.get(target_value, {target_group}))
    if independent_support >= 2:
        return VerificationDecision(
            state=ClaimState.VERIFIED,
            reason="independent_sources_agree",
            supporting_source_ids=supporting_sources,
        )

    return VerificationDecision(
        state=ClaimState.CANDIDATE,
        reason="insufficient_independent_sources",
        supporting_source_ids=supporting_sources,
    )
