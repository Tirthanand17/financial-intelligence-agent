from datetime import date
from decimal import Decimal

from app.claims.models import ClaimState, StructuredClaim
from app.claims.verification import assess_claim
from app.sources.registry import get_source_independence_group


def _claim(*, source_id: str, value: str = "5.25") -> StructuredClaim:
    source_defaults = {
        "ddnews": "DD News",
        "akashvani": "Akashvani News",
        "rbi": "Reserve Bank of India",
    }
    return StructuredClaim(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text=f"{value}%",
        value_numeric=Decimal(value),
        unit="%",
        publication_date=date(2026, 6, 5),
        effective_date=None,
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        document_id={
            "ddnews": "11111111-1111-1111-1111-111111111111",
            "akashvani": "22222222-2222-2222-2222-222222222222",
            "rbi": "33333333-3333-3333-3333-333333333333",
        }[source_id],
        evidence_text=f"RBI repo rate {value}%",
        evidence_chunk_index=0,
        entity_attribution_basis=(
            "source_default" if source_id == "rbi" else "explicit_local_alias"
        ),
        entity_source_default=source_defaults[source_id],
        confidence=0.95,
        state=ClaimState.CANDIDATE,
    )


def test_ddnews_and_akashvani_share_prasar_bharati_independence_group() -> None:
    assert get_source_independence_group("ddnews") == "prasar_bharati"
    assert get_source_independence_group("akashvani") == "prasar_bharati"


def test_sibling_prasar_bharati_brands_do_not_verify_each_other() -> None:
    ddnews = _claim(source_id="ddnews")
    akashvani = _claim(source_id="akashvani")

    decision = assess_claim(ddnews, [ddnews, akashvani])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "insufficient_independent_sources"
    assert decision.supporting_source_ids == ("akashvani", "ddnews")


def test_sibling_prasar_bharati_disagreement_is_not_false_independent_conflict() -> None:
    ddnews = _claim(source_id="ddnews", value="5.25")
    akashvani = _claim(source_id="akashvani", value="5.50")

    decision = assess_claim(ddnews, [ddnews, akashvani])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "insufficient_independent_sources"
    assert decision.conflicting_source_ids == ()


def test_rbi_plus_prasar_bharati_is_independent_agreement() -> None:
    rbi = _claim(source_id="rbi")
    ddnews = _claim(source_id="ddnews")
    akashvani = _claim(source_id="akashvani")

    decision = assess_claim(rbi, [rbi, ddnews, akashvani])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "independent_sources_agree"
    assert decision.supporting_source_ids == ("akashvani", "ddnews", "rbi")
