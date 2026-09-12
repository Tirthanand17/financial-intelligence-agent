from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.claims.models import ClaimState, StructuredClaim


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    """Result of evaluating one claim against comparable evidence.

    Phase 2 deliberately does not auto-promote anything to TRUSTED. A claim can
    become VERIFIED only when at least two independent source IDs agree on the
    same value for the same entity, metric, unit, and temporal scope. Conflicts
    are surfaced explicitly instead of being silently resolved.
    """

    state: ClaimState
    reason: str
    supporting_source_ids: tuple[str, ...] = ()
    conflicting_source_ids: tuple[str, ...] = ()


def _normalized_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def _temporal_scope(claim: StructuredClaim) -> tuple[str, date] | None:
    """Return the strongest date available for safe cross-source comparison."""
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
    # value_text is authoritative because ranges and formatted values must be
    # preserved exactly; numeric parsing is only a convenience field.
    return _normalized_text(claim.value_text)


def assess_claim(
    target: StructuredClaim,
    evidence: list[StructuredClaim],
) -> VerificationDecision:
    """Assess one claim without mutating it or writing to the database.

    Rules are intentionally conservative:
    - one source alone never verifies a claim;
    - multiple documents from the same source still count as one source;
    - no date means no automatic cross-source verification or conflict;
    - two or more independent sources that agree -> VERIFIED;
    - independent sources that disagree in the same temporal scope -> CONFLICTED;
    - TRUSTED is never assigned automatically in this layer.
    """
    if target.state in {ClaimState.REJECTED, ClaimState.SUPERSEDED}:
        return VerificationDecision(
            state=target.state,
            reason="terminal_state_preserved",
        )

    target_key = _comparison_key(target)
    if target_key is None:
        return VerificationDecision(
            state=ClaimState.CANDIDATE,
            reason="missing_temporal_scope",
            supporting_source_ids=(target.source_id,),
        )

    comparable = [claim for claim in evidence if _comparison_key(claim) == target_key]
    if not any(claim is target for claim in comparable):
        comparable.append(target)

    by_value: dict[str, set[str]] = defaultdict(set)
    for claim in comparable:
        if claim.state in {ClaimState.REJECTED, ClaimState.SUPERSEDED}:
            continue
        by_value[_value_key(claim)].add(claim.source_id)

    target_value = _value_key(target)
    supporting_sources = tuple(sorted(by_value.get(target_value, {target.source_id})))
    conflicting_sources = tuple(
        sorted(
            {
                source_id
                for value, source_ids in by_value.items()
                if value != target_value
                for source_id in source_ids
            }
        )
    )

    independent_support = len(set(supporting_sources))
    if conflicting_sources:
        return VerificationDecision(
            state=ClaimState.CONFLICTED,
            reason="independent_sources_disagree",
            supporting_source_ids=supporting_sources,
            conflicting_source_ids=conflicting_sources,
        )

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
