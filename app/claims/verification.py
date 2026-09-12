from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.claims.models import ClaimState, StructuredClaim
from app.sources.registry import get_source_independence_group


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    """Result of evaluating one claim against comparable evidence.

    A claim can become VERIFIED only when at least two independent publisher/
    institution groups agree on the same value for the same entity, metric, unit,
    and temporal scope. Multiple brands or websites owned by the same publisher
    count once. Conflicts are surfaced only when a different independent group
    disagrees; same-group duplicate/revision noise does not masquerade as an
    independent conflict.
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
    """Canonicalize safely parsed scalars while preserving text-only values.

    This lets equivalent representations such as `5.25%` and `5.25 per cent`
    agree without weakening range handling. Ranges and other values that cannot
    be represented by one scalar still compare by normalized source text.
    """
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
        # Synthetic/local test sources that are intentionally not in the trusted
        # registry remain independent by source ID.
        return source_id


def assess_claim(
    target: StructuredClaim,
    evidence: list[StructuredClaim],
) -> VerificationDecision:
    """Assess one claim without mutating it or writing to the database.

    Rules are intentionally conservative:
    - one independent publisher/institution group alone never verifies a claim;
    - multiple documents or brands from the same group still count as one;
    - no date means no automatic cross-source verification or conflict;
    - two or more independent groups that agree -> VERIFIED;
    - a different independent group that disagrees in the same scope -> CONFLICTED;
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
