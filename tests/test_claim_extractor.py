from datetime import date
from decimal import Decimal

from app.claims.extractor import extract_structured_claims
from app.claims.models import ClaimState


def _extract(chunks: list[str]):
    return extract_structured_claims(
        chunks=chunks,
        document_id="11111111-1111-1111-1111-111111111111",
        source_id="rbi",
        source_url="https://www.rbi.org.in/",
        entity="Reserve Bank of India",
    )


def test_extracts_repo_rate_from_rbi_style_line() -> None:
    claims = _extract(["Policy Rates\nPolicy Repo Rate : 5.25%\nBank Rate : 5.50%"])

    repo = next(claim for claim in claims if claim.metric == "Policy Repo Rate")
    assert repo.value_text == "5.25%"
    assert repo.value_numeric == Decimal("5.25")
    assert repo.unit == "%"
    assert repo.state is ClaimState.CANDIDATE
    assert repo.evidence_text == "Policy Repo Rate : 5.25%"
    assert repo.evidence_chunk_index == 0


def test_extracts_repo_rate_from_rbi_split_html_rows() -> None:
    claims = _extract(
        [
            "Current\nRates\nPolicy Rates\nPolicy Repo Rate\n:\n5.25%\n"
            "Standing Deposit Facility Rate\n:\n5.00%"
        ]
    )

    extracted = {claim.metric: claim for claim in claims}

    repo = extracted["Policy Repo Rate"]
    assert repo.value_text == "5.25%"
    assert repo.value_numeric == Decimal("5.25")
    assert repo.unit == "%"
    assert repo.evidence_text == "Policy Repo Rate\n:\n5.25%"

    sdf = extracted["Standing Deposit Facility Rate"]
    assert sdf.value_text == "5.00%"


def test_extracts_multiple_explicit_rbi_metrics() -> None:
    claims = _extract(["Reserve Ratios\nCRR : 3.00%\nSLR : 18.00%"])

    extracted = {claim.metric: claim.value_text for claim in claims}
    assert extracted == {"CRR": "3.00%", "SLR": "18.00%"}


def test_does_not_turn_navigation_headings_into_claims() -> None:
    claims = _extract(["RBI Regulated Entities\nMonetary Policy\nPolicy Repo Rate\nFAQs"])

    assert claims == []


def test_rejects_period_heading_that_looks_like_numeric_range() -> None:
    claims = _extract(
        ["Performance of Private Corporate Business Sector during Q1 : 2026-27"]
    )

    assert claims == []


def test_range_is_preserved_without_fake_scalar_value() -> None:
    claims = _extract(["Lending / Deposit Rates\nBase Rate : 8.40% - 10.00%"])

    assert len(claims) == 1
    assert claims[0].value_text == "8.40% - 10.00%"
    assert claims[0].value_numeric is None
    assert claims[0].unit == "%"


def test_attaches_nearby_effective_date_to_split_claim() -> None:
    claims = _extract(
        [
            "Effective Date\n12 September 2026\n"
            "Policy Repo Rate\n:\n5.25%"
        ]
    )

    assert len(claims) == 1
    assert claims[0].effective_date == date(2026, 9, 12)
    assert claims[0].publication_date is None


def test_attaches_nearby_publication_date_to_one_line_claim() -> None:
    claims = _extract(
        ["Publication Date\n2026-09-12\nPolicy Repo Rate : 5.25%"]
    )

    assert len(claims) == 1
    assert claims[0].publication_date == date(2026, 9, 12)
    assert claims[0].effective_date is None


def test_does_not_attach_distant_unrelated_date() -> None:
    claims = _extract(
        [
            "Publication Date\n2026-09-12\nUnrelated Section\nNavigation\n"
            "Another Heading\nPolicy Repo Rate\n:\n5.25%"
        ]
    )

    assert len(claims) == 1
    assert claims[0].publication_date is None
    assert claims[0].effective_date is None
