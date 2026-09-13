from dataclasses import dataclass

from app.claims.eligibility import claim_quality_rejection_reason
from app.claims.models import ClaimState, StructuredClaim
from app.sources.registry import (
    AuthorityLevel,
    get_source,
    get_source_independence_group,
)


@dataclass(frozen=True, slots=True)
class TrustDecision:
    """Pure decision describing whether a verified claim may become trusted."""

    state: ClaimState
    reason: str
    corroborating_source_ids: tuple[str, ...] = ()


def _normalized(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def _temporal_scope(claim: StructuredClaim) -> tuple[str, str] | None:
    if claim.effective_date is not None:
        return ("effective", claim.effective_date.isoformat())
    if claim.publication_date is not None:
        return ("publication", claim.publication_date.isoformat())
    return None


def _comparison_key(claim: StructuredClaim) -> tuple[str, str, str, tuple[str, str] | None]:
    return (
        _normalized(claim.entity),
        _normalized(claim.metric),
        _normalized(claim.unit),
        _temporal_scope(claim),
    )


def _value_key(claim: StructuredClaim) -> str:
    if claim.value_numeric is not None:
        return f"numeric:{claim.value_numeric.normalize()}:{_normalized(claim.unit)}"
    return f"text:{_normalized(claim.value_text)}"


def _source_definition(claim: StructuredClaim):
    try:
        return get_source(claim.source_id)
    except ValueError:
        return None


def _source_group(source_id: str) -> str:
    try:
        return get_source_independence_group(source_id)
    except ValueError:
        return source_id


def _quality_ok(claim: StructuredClaim) -> bool:
    return claim_quality_rejection_reason(claim.metric, claim.evidence_text) is None


def _has_auditable_entity_attribution(claim: StructuredClaim) -> bool:
    """Return whether the claim's subject assignment is safe for trust policy."""
    source = _source_definition(claim)
    if source is None or claim.entity_source_default is None:
        return False

    if _normalized(claim.entity_source_default) != _normalized(source.name):
        return False

    source_is_subject = _normalized(source.name) == _normalized(claim.entity)
    if source_is_subject:
        return claim.entity_attribution_basis in {
            "source_default",
            "explicit_local_alias",
        }

    return claim.entity_attribution_basis == "explicit_local_alias"


def assess_trust(
    target: StructuredClaim,
    evidence: list[StructuredClaim],
) -> TrustDecision:
    """Assess conservative automatic promotion from VERIFIED to TRUSTED.

    Trust is stronger than verification. Phase 16 also requires both the target
    and every corroborating/conflicting item considered by this decision to pass
    the narrow structured-claim quality floor. Historical quality-failed rows are
    preserved, but they cannot create new TRUSTED knowledge.
    """
    if target.state is ClaimState.TRUSTED:
        return TrustDecision(
            state=ClaimState.TRUSTED,
            reason="already_trusted",
        )

    if target.state is not ClaimState.VERIFIED:
        return TrustDecision(
            state=target.state,
            reason="target_not_verified",
        )

    if not _quality_ok(target):
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="quality_gate_failed",
        )

    target_scope = _temporal_scope(target)
    if target_scope is None:
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="missing_temporal_scope",
        )

    target_source = _source_definition(target)
    if target_source is None:
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="unknown_target_source",
        )

    if target_source.authority_level is not AuthorityLevel.A:
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="target_source_not_authority_a",
        )

    if _normalized(target_source.name) != _normalized(target.entity):
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="target_not_direct_primary_entity",
        )

    if not _has_auditable_entity_attribution(target):
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="target_entity_attribution_not_auditable",
        )

    target_key = _comparison_key(target)
    target_value = _value_key(target)
    target_group = _source_group(target.source_id)

    comparable = [
        claim
        for claim in evidence
        if _quality_ok(claim)
        and _comparison_key(claim) == target_key
        and claim.state not in {ClaimState.REJECTED, ClaimState.SUPERSEDED}
    ]

    if any(
        _value_key(claim) != target_value
        and _source_group(claim.source_id) != target_group
        for claim in comparable
    ):
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="active_comparable_value_conflict",
        )

    qualified_groups: set[str] = set()
    qualified_sources: set[str] = set()
    for claim in comparable:
        claim_group = _source_group(claim.source_id)
        if claim_group == target_group:
            continue
        if claim.state not in {ClaimState.VERIFIED, ClaimState.TRUSTED}:
            continue
        if _value_key(claim) != target_value:
            continue

        source = _source_definition(claim)
        if source is None or source.authority_level not in {
            AuthorityLevel.A,
            AuthorityLevel.B,
        }:
            continue
        if not _has_auditable_entity_attribution(claim):
            continue

        qualified_groups.add(claim_group)
        qualified_sources.add(claim.source_id)

    if not qualified_groups:
        return TrustDecision(
            state=ClaimState.VERIFIED,
            reason="insufficient_qualified_corroboration",
        )

    return TrustDecision(
        state=ClaimState.TRUSTED,
        reason="verified_primary_with_independent_authoritative_corroboration",
        corroborating_source_ids=tuple(sorted(qualified_sources)),
    )
