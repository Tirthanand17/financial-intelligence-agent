from datetime import date

from app.claims.models import ClaimState, StructuredClaim
from app.claims.versioning import assess_supersession


def _claim(
    *,
    document_id: str,
    source_id: str = "rbi",
    metric: str = "Policy Repo Rate",
    value_text: str = "5.25%",
    unit: str | None = "%",
    publication_date: date | None = None,
    effective_date: date | None = None,
    state: ClaimState = ClaimState.CANDIDATE,
) -> StructuredClaim:
    return StructuredClaim(
        entity="Reserve Bank of India",
        metric=metric,
        value_text=value_text,
        value_numeric=None,
        unit=unit,
        publication_date=publication_date,
        effective_date=effective_date,
        source_id=source_id,
        source_url="https://www.rbi.org.in/",
        document_id=document_id,
        evidence_text=f"{metric} : {value_text}",
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
    )


def test_newer_effective_date_supersedes_older_source_local_claim() -> None:
    older = _claim(
        document_id="11111111-1111-1111-1111-111111111111",
        value_text="5.50%",
        effective_date=date(2026, 1, 1),
    )
    newer = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        value_text="5.25%",
        effective_date=date(2026, 2, 1),
    )

    decision = assess_supersession(older, newer)

    assert decision.state is ClaimState.SUPERSEDED
    assert decision.reason == "newer_source_local_version"
    assert decision.temporal_kind == "effective"
    assert decision.superseded_by_document_id == newer.document_id


def test_later_publication_snapshot_can_supersede_when_no_effective_dates_exist() -> None:
    older = _claim(
        document_id="11111111-1111-1111-1111-111111111111",
        publication_date=date(2026, 1, 10),
    )
    newer = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        publication_date=date(2026, 1, 20),
    )

    decision = assess_supersession(older, newer)

    assert decision.state is ClaimState.SUPERSEDED
    assert decision.temporal_kind == "publication"


def test_same_value_still_allows_later_snapshot_to_supersede() -> None:
    older = _claim(
        document_id="11111111-1111-1111-1111-111111111111",
        value_text="5.25%",
        effective_date=date(2026, 1, 1),
    )
    newer = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        value_text="5.25%",
        effective_date=date(2026, 2, 1),
    )

    assert assess_supersession(older, newer).state is ClaimState.SUPERSEDED


def test_cross_source_claim_never_supersedes_here() -> None:
    older = _claim(
        document_id="11111111-1111-1111-1111-111111111111",
        source_id="rbi",
        effective_date=date(2026, 1, 1),
    )
    newer = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        source_id="imf",
        effective_date=date(2026, 2, 1),
    )

    decision = assess_supersession(older, newer)

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "different_series_or_source"


def test_mixed_temporal_semantics_do_not_supersede() -> None:
    older = _claim(
        document_id="11111111-1111-1111-1111-111111111111",
        effective_date=date(2026, 1, 1),
    )
    newer = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        publication_date=date(2026, 2, 1),
    )

    decision = assess_supersession(older, newer)

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "incompatible_or_missing_temporal_scope"


def test_equal_or_earlier_date_does_not_supersede() -> None:
    older = _claim(
        document_id="11111111-1111-1111-1111-111111111111",
        effective_date=date(2026, 2, 1),
    )
    newer = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        effective_date=date(2026, 2, 1),
    )

    decision = assess_supersession(older, newer)

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "newer_date_not_later"


def test_conflicted_newer_claim_cannot_supersede_history() -> None:
    older = _claim(
        document_id="11111111-1111-1111-1111-111111111111",
        effective_date=date(2026, 1, 1),
    )
    newer = _claim(
        document_id="22222222-2222-2222-2222-222222222222",
        effective_date=date(2026, 2, 1),
        state=ClaimState.CONFLICTED,
    )

    decision = assess_supersession(older, newer)

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "newer_claim_not_eligible"
