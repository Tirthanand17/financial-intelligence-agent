from datetime import date
from decimal import Decimal

from app.claims.eligibility import filter_eligible_claims, is_claim_eligible
from app.claims.models import ClaimState, StructuredClaim


def _claim(
    *,
    source_id: str,
    entity: str,
    attribution_basis: str,
    metric: str = "Policy Repo Rate",
) -> StructuredClaim:
    source_default = {
        "rbi": "Reserve Bank of India",
        "ddnews": "DD News",
        "imf": "International Monetary Fund",
    }[source_id]
    return StructuredClaim(
        entity=entity,
        metric=metric,
        value_text="5.25%",
        value_numeric=Decimal("5.25"),
        unit="%",
        publication_date=date(2026, 6, 5),
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        document_id="11111111-1111-1111-1111-111111111111",
        evidence_text="Policy Repo Rate = 5.25%",
        evidence_chunk_index=0,
        entity_attribution_basis=attribution_basis,
        entity_source_default=source_default,
        entity_matched_aliases=("RBI",) if attribution_basis == "explicit_local_alias" else (),
        entity_evidence_text="RBI\nPolicy Repo Rate = 5.25%",
        confidence=0.95,
        state=ClaimState.CANDIDATE,
    )


def test_direct_central_bank_repo_rate_is_eligible() -> None:
    claim = _claim(
        source_id="rbi",
        entity="Reserve Bank of India",
        attribution_basis="source_default",
    )

    assert is_claim_eligible(claim)


def test_secondary_repo_rate_requires_explicit_subject_attribution() -> None:
    claim = _claim(
        source_id="ddnews",
        entity="DD News",
        attribution_basis="source_default",
    )

    assert not is_claim_eligible(claim)


def test_secondary_repo_rate_with_explicit_rbi_alias_is_eligible() -> None:
    claim = _claim(
        source_id="ddnews",
        entity="Reserve Bank of India",
        attribution_basis="explicit_local_alias",
    )

    assert is_claim_eligible(claim)


def test_non_repo_metric_is_not_subject_locked_by_this_gate() -> None:
    claim = _claim(
        source_id="ddnews",
        entity="DD News",
        attribution_basis="source_default",
        metric="GDP Growth",
    )

    assert is_claim_eligible(claim)


def test_filter_preserves_only_safe_candidates_and_order() -> None:
    unsafe = _claim(
        source_id="ddnews",
        entity="DD News",
        attribution_basis="source_default",
    )
    safe_secondary = _claim(
        source_id="ddnews",
        entity="Reserve Bank of India",
        attribution_basis="explicit_local_alias",
    )
    safe_primary = _claim(
        source_id="rbi",
        entity="Reserve Bank of India",
        attribution_basis="source_default",
    )

    assert filter_eligible_claims([unsafe, safe_secondary, safe_primary]) == [
        safe_secondary,
        safe_primary,
    ]
