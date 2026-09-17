from datetime import date
from decimal import Decimal

from app.claims.eligibility import (
    claim_quality_rejection_reason,
    filter_eligible_claims,
    is_claim_eligible,
)
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


def test_quality_floor_rejects_page_contact_and_identifier_metadata_metrics() -> None:
    base = _claim(
        source_id="ddnews",
        entity="DD News",
        attribution_basis="source_default",
        metric="GDP Growth",
    )
    for metric in (
        "Posted On",
        "Release ID",
        "Visitor Counter",
        "Date",
        "Phone no",
        "Scrip Code",
        "Email",
        "Fax No",
        "GSTIN",
        "Last Updated",
        "Page Number",
        "Serial No",
        "Sr. No",
        "S. No",
        "Telephone Number",
        "Time",
        "Toll Free No",
        "Website URL",
    ):
        candidate = base.model_copy(update={"metric": metric})
        assert claim_quality_rejection_reason(metric, candidate.evidence_text) == "metadata_metric"
        assert not is_claim_eligible(candidate)


def test_quality_floor_rejects_numbered_page_and_serial_labels_only() -> None:
    for metric in ("Page 3", "Page No. 12", "Serial No 7", "Sr. 9", "S. No 4"):
        assert claim_quality_rejection_reason(metric, f"{metric}: 5") == "metadata_metric"

    # The regex must stay anchored to known metadata stems so legitimate numbered
    # economic/financial metrics are not removed merely because they contain a number.
    for metric in ("10-Year G-Sec Yield", "Tier 1 Capital Ratio", "M3 Growth"):
        assert claim_quality_rejection_reason(metric, f"{metric}: 5.25%") is None


def test_quality_floor_rejects_short_and_month_heading_fragments() -> None:
    base = _claim(
        source_id="ddnews",
        entity="DD News",
        attribution_basis="source_default",
        metric="GDP Growth",
    )
    assert not is_claim_eligible(base.model_copy(update={"metric": "r."}))
    assert not is_claim_eligible(base.model_copy(update={"metric": "i r."}))
    assert not is_claim_eligible(base.model_copy(update={"metric": "SEP 2026 2"}))


def test_quality_floor_rejects_schedule_colon_fragments_but_keeps_financial_metric() -> None:
    base = _claim(
        source_id="ddnews",
        entity="DD News",
        attribution_basis="source_default",
        metric="GDP Growth",
    )
    schedule_fragment = base.model_copy(
        update={
            "metric": "am and 10",
            "evidence_text": "Applications between 9:30 am and 10:30 am are accepted.",
        }
    )
    assert claim_quality_rejection_reason(
        schedule_fragment.metric, schedule_fragment.evidence_text
    ) == "schedule_time_fragment"
    assert not is_claim_eligible(schedule_fragment)
    assert is_claim_eligible(base)


def test_quality_floor_keeps_legitimate_financial_metric_shapes() -> None:
    for metric in (
        "CRR",
        "SLR",
        "OI",
        "PE",
        "P/E",
        "MCLR (Overnight)",
        "10-Year G-Sec Yield",
        "GDP Growth",
        "Current Account Deficit",
        "Consumer Price Index",
        "Fiscal Deficit",
        "Foreign Exchange Reserves",
    ):
        assert claim_quality_rejection_reason(metric, f"{metric}: 5.25%") is None
