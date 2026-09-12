from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.storage import save_claim
from app.claims.verification_storage import reconcile_verification_for_claim
from app.storage.database import Base, ClaimRecord, ClaimVerificationEventRecord


def _claim(
    *,
    source_id: str,
    document_id: str,
    value_text: str = "5.25%",
    effective_date: date | None = date(2026, 9, 12),
    publication_date: date | None = None,
    state: ClaimState = ClaimState.CANDIDATE,
) -> StructuredClaim:
    return StructuredClaim(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text=value_text,
        value_numeric=Decimal(value_text.rstrip("%")),
        unit="%",
        publication_date=publication_date,
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


def test_independent_agreement_verifies_both_claims_and_audits() -> None:
    engine = _engine()

    with Session(engine) as session:
        first, _ = save_claim(
            session,
            _claim(source_id="rbi", document_id="11111111-1111-1111-1111-111111111111"),
        )
        second, _ = save_claim(
            session,
            _claim(source_id="imf", document_id="22222222-2222-2222-2222-222222222222"),
        )

        events = reconcile_verification_for_claim(session, second)
        states = list(session.scalars(select(ClaimRecord.state).order_by(ClaimRecord.source_id)))

    assert states == ["verified", "verified"]
    assert len(events) == 2
    assert {event.to_state for event in events} == {"verified"}
    assert {event.reason for event in events} == {"independent_sources_agree"}


def test_independent_disagreement_marks_both_conflicted_and_audits() -> None:
    engine = _engine()

    with Session(engine) as session:
        first, _ = save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.25%",
            ),
        )
        second, _ = save_claim(
            session,
            _claim(
                source_id="imf",
                document_id="22222222-2222-2222-2222-222222222222",
                value_text="5.50%",
            ),
        )

        events = reconcile_verification_for_claim(session, second)
        states = list(session.scalars(select(ClaimRecord.state)))

    assert states == ["conflicted", "conflicted"]
    assert len(events) == 2
    assert {event.to_state for event in events} == {"conflicted"}
    assert {event.reason for event in events} == {"independent_sources_disagree"}


def test_same_source_duplicate_does_not_verify() -> None:
    engine = _engine()

    with Session(engine) as session:
        first, _ = save_claim(
            session,
            _claim(source_id="rbi", document_id="11111111-1111-1111-1111-111111111111"),
        )
        second, _ = save_claim(
            session,
            _claim(source_id="rbi", document_id="22222222-2222-2222-2222-222222222222"),
        )

        events = reconcile_verification_for_claim(session, second)
        states = list(session.scalars(select(ClaimRecord.state)))

    assert states == ["candidate", "candidate"]
    assert events == []


def test_missing_temporal_scope_remains_candidate_without_audit() -> None:
    engine = _engine()

    with Session(engine) as session:
        first, _ = save_claim(
            session,
            _claim(
                source_id="rbi",
                document_id="11111111-1111-1111-1111-111111111111",
                effective_date=None,
                publication_date=None,
            ),
        )
        second, _ = save_claim(
            session,
            _claim(
                source_id="imf",
                document_id="22222222-2222-2222-2222-222222222222",
                effective_date=None,
                publication_date=None,
            ),
        )

        events = reconcile_verification_for_claim(session, second)
        states = list(session.scalars(select(ClaimRecord.state)))

    assert states == ["candidate", "candidate"]
    assert events == []


def test_reconciliation_is_idempotent_after_state_transition() -> None:
    engine = _engine()

    with Session(engine) as session:
        first, _ = save_claim(
            session,
            _claim(source_id="rbi", document_id="11111111-1111-1111-1111-111111111111"),
        )
        second, _ = save_claim(
            session,
            _claim(source_id="imf", document_id="22222222-2222-2222-2222-222222222222"),
        )

        initial_events = reconcile_verification_for_claim(session, second)
        repeated_events = reconcile_verification_for_claim(session, second)
        event_count = session.scalar(
            select(func.count()).select_from(ClaimVerificationEventRecord)
        )

    assert len(initial_events) == 2
    assert repeated_events == []
    assert event_count == 2
