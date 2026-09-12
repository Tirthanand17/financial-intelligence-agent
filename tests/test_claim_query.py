from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.query import resolve_structured_claim_question
from app.claims.storage import save_claim
from app.storage.database import Base, ClaimRecord


def _claim(
    *,
    source_id: str,
    document_id: str,
    value_text: str = "5.25%",
    effective_date: date | None = date(2026, 9, 12),
    state: ClaimState = ClaimState.CANDIDATE,
) -> StructuredClaim:
    return StructuredClaim(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text=value_text,
        value_numeric=Decimal(value_text.rstrip("%")),
        unit="%",
        effective_date=effective_date,
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        document_id=document_id,
        evidence_text=f"Policy Repo Rate : {value_text}",
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
    )


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_verified_claim_is_preferred_for_structured_answer() -> None:
    engine = _engine()
    with Session(engine) as session:
        save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
                state=ClaimState.CANDIDATE,
            ),
        )
        save_claim(
            session,
            _claim(
                source_id="imf",
                document_id="22222222-2222-2222-2222-222222222222",
                state=ClaimState.VERIFIED,
            ),
        )

        result = resolve_structured_claim_question(session, "What is the policy repo rate?")

    assert result is not None
    assert result.status == "answer"
    assert result.answer == "Policy Repo Rate : 5.25%"
    assert result.confidence == "high"
    assert result.confidence_basis == "verified_structured_claim"


def test_conflicted_claims_are_not_presented_as_single_fact() -> None:
    engine = _engine()
    with Session(engine) as session:
        save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.25%",
                state=ClaimState.CONFLICTED,
            ),
        )
        save_claim(
            session,
            _claim(
                source_id="imf",
                document_id="22222222-2222-2222-2222-222222222222",
                value_text="5.50%",
                state=ClaimState.CONFLICTED,
            ),
        )

        result = resolve_structured_claim_question(session, "What is the policy repo rate?")

    assert result is not None
    assert result.status == "conflict"
    assert result.confidence == "low"
    assert result.confidence_basis == "conflicting_structured_claims"
    assert len(result.evidence) == 2


def test_superseded_claim_is_not_used_as_current_fact() -> None:
    engine = _engine()
    with Session(engine) as session:
        save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.50%",
                state=ClaimState.SUPERSEDED,
            ),
        )

        result = resolve_structured_claim_question(session, "What is the policy repo rate?")

    assert result is not None
    assert result.status == "no_active_claim"
    assert result.confidence_basis == "only_rejected_or_superseded_structured_claims"


def test_latest_temporal_scope_wins_over_older_verified_value() -> None:
    engine = _engine()
    with Session(engine) as session:
        save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.50%",
                effective_date=date(2026, 8, 1),
                state=ClaimState.VERIFIED,
            ),
        )
        save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="22222222-2222-2222-2222-222222222222",
                value_text="5.25%",
                effective_date=date(2026, 9, 1),
                state=ClaimState.CANDIDATE,
            ),
        )

        result = resolve_structured_claim_question(session, "What is the latest policy repo rate?")

    assert result is not None
    assert result.answer == "Policy Repo Rate : 5.25%"
    assert result.confidence == "medium"
    assert result.confidence_basis == "candidate_structured_claim"


def test_source_filter_limits_structured_resolution() -> None:
    engine = _engine()
    with Session(engine) as session:
        save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.25%",
                state=ClaimState.CANDIDATE,
            ),
        )
        save_claim(
            session,
            _claim(
                source_id="imf",
                document_id="22222222-2222-2222-2222-222222222222",
                value_text="5.50%",
                state=ClaimState.CANDIDATE,
            ),
        )

        result = resolve_structured_claim_question(
            session,
            "What is the policy repo rate?",
            source_id="rbi",
        )

    assert result is not None
    assert result.answer == "Policy Repo Rate : 5.25%"
    assert {item["source_id"] for item in result.evidence} == {"rbi"}


def test_structured_evidence_exposes_entity_attribution_provenance() -> None:
    engine = _engine()
    claim = _claim(
        source_id="ddnews",
        document_id="33333333-3333-3333-3333-333333333333",
        state=ClaimState.VERIFIED,
    ).model_copy(
        update={
            "entity_attribution_basis": "explicit_local_alias",
            "entity_source_default": "DD News",
            "entity_matched_aliases": ("RBI",),
            "entity_evidence_text": "RBI Policy Repo Rate : 5.25%",
        }
    )

    with Session(engine) as session:
        save_claim(session, claim)
        result = resolve_structured_claim_question(
            session,
            "What is the policy repo rate?",
        )

    assert result is not None
    assert result.status == "answer"
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence["entity_attribution_basis"] == "explicit_local_alias"
    assert evidence["entity_source_default"] == "DD News"
    assert evidence["entity_matched_aliases"] == ("RBI",)
    assert evidence["entity_ambiguous_candidates"] == ()
    assert evidence["entity_attribution_evidence"] == "RBI Policy Repo Rate : 5.25%"


def test_unrelated_question_falls_back_to_other_retrieval() -> None:
    engine = _engine()
    with Session(engine) as session:
        save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
            ),
        )
        result = resolve_structured_claim_question(session, "What does the handbook explain?")

    assert result is None
