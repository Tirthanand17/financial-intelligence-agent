from datetime import date
from decimal import Decimal

from app.claims.models import ClaimState, StructuredClaim
from app.claims.verification import assess_claim


def _claim(**overrides) -> StructuredClaim:
    data = {
        "entity": "Reserve Bank of India",
        "metric": "Policy Repo Rate",
        "value_text": "5.25%",
        "value_numeric": Decimal("5.25"),
        "unit": "%",
        "publication_date": None,
        "effective_date": date(2026, 9, 12),
        "source_id": "rbi",
        "source_url": "https://www.rbi.org.in/",
        "document_id": "11111111-1111-1111-1111-111111111111",
        "evidence_text": "Policy Repo Rate\n:\n5.25%",
        "evidence_chunk_index": 0,
        "confidence": 0.95,
        "state": ClaimState.CANDIDATE,
    }
    data.update(overrides)
    return StructuredClaim(**data)


def test_single_source_remains_candidate() -> None:
    target = _claim()

    decision = assess_claim(target, [target])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "insufficient_independent_sources"


def test_two_documents_from_same_source_do_not_verify() -> None:
    target = _claim()
    duplicate_source = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        source_url="https://www.rbi.org.in/another-page",
    )

    decision = assess_claim(target, [target, duplicate_source])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.supporting_source_ids == ("rbi",)


def test_two_independent_sources_agree_and_verify() -> None:
    target = _claim()
    corroborating = _claim(
        source_id="world_bank",
        source_url="https://www.worldbank.org/example",
        document_id="22222222-2222-2222-2222-222222222222",
    )

    decision = assess_claim(target, [target, corroborating])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "independent_sources_agree"
    assert decision.supporting_source_ids == ("rbi", "world_bank")


def test_equivalent_percent_wording_verifies_by_numeric_value() -> None:
    target = _claim()
    corroborating = _claim(
        source_id="ddnews",
        source_url="https://ddnews.gov.in/en/example/",
        document_id="22222222-2222-2222-2222-222222222222",
        value_text="5.25 per cent",
        value_numeric=Decimal("5.25"),
        evidence_text="RBI keeps repo rate unchanged at 5.25 per cent",
    )

    decision = assess_claim(target, [target, corroborating])

    assert decision.state is ClaimState.VERIFIED
    assert decision.supporting_source_ids == ("ddnews", "rbi")


def test_same_scope_disagreement_is_conflicted() -> None:
    target = _claim()
    conflicting = _claim(
        source_id="world_bank",
        source_url="https://www.worldbank.org/example",
        document_id="22222222-2222-2222-2222-222222222222",
        value_text="5.50%",
        value_numeric=Decimal("5.50"),
        evidence_text="Policy Repo Rate : 5.50%",
    )

    decision = assess_claim(target, [target, conflicting])

    assert decision.state is ClaimState.CONFLICTED
    assert decision.reason == "independent_sources_disagree"
    assert decision.conflicting_source_ids == ("world_bank",)


def test_different_effective_dates_are_not_conflicts() -> None:
    target = _claim(effective_date=date(2026, 9, 12))
    older = _claim(
        source_id="world_bank",
        source_url="https://www.worldbank.org/example",
        document_id="22222222-2222-2222-2222-222222222222",
        effective_date=date(2026, 8, 1),
        value_text="5.50%",
        value_numeric=Decimal("5.50"),
    )

    decision = assess_claim(target, [target, older])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "insufficient_independent_sources"


def test_missing_date_blocks_automatic_verification() -> None:
    target = _claim(effective_date=None, publication_date=None)
    corroborating = _claim(
        source_id="world_bank",
        source_url="https://www.worldbank.org/example",
        document_id="22222222-2222-2222-2222-222222222222",
        effective_date=None,
        publication_date=None,
    )

    decision = assess_claim(target, [target, corroborating])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "missing_temporal_scope"


def test_terminal_rejected_state_is_preserved() -> None:
    target = _claim(state=ClaimState.REJECTED)

    decision = assess_claim(target, [target])

    assert decision.state is ClaimState.REJECTED
    assert decision.reason == "terminal_state_preserved"
