from app.claims.extractor import extract_structured_claims
from app.claims.models import ClaimState
from app.claims.verification import assess_claim


def _extract(
    *,
    source_id: str,
    source_url: str,
    entity: str,
    document_id: str,
    text: str,
):
    claims = extract_structured_claims(
        chunks=[text],
        document_id=document_id,
        source_id=source_id,
        source_url=source_url,
        entity=entity,
    )
    assert len(claims) == 1
    return claims[0]


def test_explicit_secondary_rbi_subject_can_verify_primary_rbi_claim() -> None:
    primary = _extract(
        source_id="rbi",
        source_url="https://www.rbi.org.in/",
        entity="Reserve Bank of India",
        document_id="11111111-1111-1111-1111-111111111111",
        text="Effective Date\n2026-09-12\nPolicy Repo Rate : 5.25%",
    )
    secondary = _extract(
        source_id="imf",
        source_url="https://www.imf.org/example",
        entity="International Monetary Fund",
        document_id="22222222-2222-2222-2222-222222222222",
        text="RBI\nEffective Date\n2026-09-12\nPolicy Repo Rate : 5.25%",
    )

    assert primary.entity == secondary.entity == "Reserve Bank of India"
    assert primary.metric == secondary.metric == "Policy Repo Rate"

    decision = assess_claim(primary, [primary, secondary])

    assert decision.state is ClaimState.VERIFIED
    assert decision.supporting_source_ids == ("imf", "rbi")


def test_entity_prefixed_secondary_metric_aligns_with_primary_metric() -> None:
    primary = _extract(
        source_id="rbi",
        source_url="https://www.rbi.org.in/",
        entity="Reserve Bank of India",
        document_id="11111111-1111-1111-1111-111111111111",
        text="Effective Date\n2026-09-12\nPolicy Repo Rate : 5.25%",
    )
    secondary = _extract(
        source_id="world_bank",
        source_url="https://www.worldbank.org/example",
        entity="World Bank",
        document_id="22222222-2222-2222-2222-222222222222",
        text="Effective Date\n2026-09-12\nRBI Policy Repo Rate : 5.25%",
    )

    assert secondary.entity == "Reserve Bank of India"
    assert secondary.metric == "Policy Repo Rate"
    assert assess_claim(primary, [primary, secondary]).state is ClaimState.VERIFIED


def test_ambiguous_secondary_subject_does_not_cross_verify() -> None:
    primary = _extract(
        source_id="rbi",
        source_url="https://www.rbi.org.in/",
        entity="Reserve Bank of India",
        document_id="11111111-1111-1111-1111-111111111111",
        text="Effective Date\n2026-09-12\nPolicy Repo Rate : 5.25%",
    )
    ambiguous = _extract(
        source_id="imf",
        source_url="https://www.imf.org/example",
        entity="International Monetary Fund",
        document_id="22222222-2222-2222-2222-222222222222",
        text="IMF and RBI\nEffective Date\n2026-09-12\nPolicy Repo Rate : 5.25%",
    )

    assert ambiguous.entity == "International Monetary Fund"

    decision = assess_claim(primary, [primary, ambiguous])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "insufficient_independent_sources"
