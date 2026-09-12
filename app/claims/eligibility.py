from app.claims.models import StructuredClaim
from app.sources.registry import get_source


def _normalized(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def is_claim_eligible(claim: StructuredClaim) -> bool:
    """Return whether an extracted claim is safe to persist as a candidate.

    Extraction is intentionally permissive enough to preserve useful explicit
    evidence, but a few metrics carry a strong subject meaning. The policy repo
    rate is one such metric: a source that is itself a central bank may own the
    metric directly, while a secondary source may only attribute it to another
    entity when that subject is named explicitly in the local evidence.

    This gate prevents a news article from accidentally creating a claim such as
    `DD News | Policy Repo Rate = 5.25%` merely because an isolated sentence lost
    the nearby RBI subject during chunking. The raw document and chunks remain
    preserved; only the unsafe structured claim is withheld.
    """
    if _normalized(claim.metric) != "policy repo rate":
        return True

    try:
        source = get_source(claim.source_id)
    except ValueError:
        return False

    source_is_subject = _normalized(source.name) == _normalized(claim.entity)
    if source_is_subject:
        return (
            source.category == "central_bank"
            and claim.entity_attribution_basis
            in {"source_default", "explicit_local_alias"}
        )

    return claim.entity_attribution_basis == "explicit_local_alias"


def filter_eligible_claims(claims: list[StructuredClaim]) -> list[StructuredClaim]:
    """Preserve order while dropping unsafe structured candidates."""
    return [claim for claim in claims if is_claim_eligible(claim)]
