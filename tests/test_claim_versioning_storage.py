from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.storage import save_claim
from app.claims.versioning_storage import apply_supersession_for_newer_claim
from app.storage.database import Base, ClaimRecord, ClaimSupersessionRecord


def _claim(
    *,
    document_id: str,
    value_text: str = "5.25%",
    source_id: str = "rbi",
    effective_date: date | None = None,
    publication_date: date | None = None,
) -> StructuredClaim:
    numeric = Decimal(value_text.rstrip("%"))
    return StructuredClaim(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text=value_text,
        value_numeric=numeric,
        unit="%",
        publication_date=publication_date,
        effective_date=effective_date,
        source_id=source_id,
        source_url="https://www.rbi.org.in/",
        document_id=document_id,
        evidence_text=f"Policy Repo Rate : {value_text}",
        evidence_chunk_index=0,
        confidence=0.95,
        state=ClaimState.CANDIDATE,
    )


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_supersession_is_persisted_without_deleting_history() -> None:
    with _session() as session:
        older, _ = save_claim(
            session,
            _claim(
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.50%",
                effective_date=date(2026, 1, 1),
            ),
        )
        newer, _ = save_claim(
            session,
            _claim(
                document_id="22222222-2222-2222-2222-222222222222",
                value_text="5.25%",
                effective_date=date(2026, 2, 1),
            ),
        )

        created = apply_supersession_for_newer_claim(session, newer)

        claim_count = session.scalar(select(func.count()).select_from(ClaimRecord))
        audit = session.scalar(select(ClaimSupersessionRecord))
        session.refresh(older)

        assert len(created) == 1
        assert claim_count == 2
        assert older.state == ClaimState.SUPERSEDED.value
        assert newer.state == ClaimState.CANDIDATE.value
        assert audit is not None
        assert audit.older_claim_id == older.id
        assert audit.newer_claim_id == newer.id
        assert audit.newer_document_id == newer.document_id
        assert audit.temporal_kind == "effective"
        assert audit.older_date == date(2026, 1, 1)
        assert audit.newer_date == date(2026, 2, 1)


def test_persistent_supersession_is_idempotent() -> None:
    with _session() as session:
        _older, _ = save_claim(
            session,
            _claim(
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.50%",
                effective_date=date(2026, 1, 1),
            ),
        )
        newer, _ = save_claim(
            session,
            _claim(
                document_id="22222222-2222-2222-2222-222222222222",
                value_text="5.25%",
                effective_date=date(2026, 2, 1),
            ),
        )

        first = apply_supersession_for_newer_claim(session, newer)
        second = apply_supersession_for_newer_claim(session, newer)
        audit_count = session.scalar(
            select(func.count()).select_from(ClaimSupersessionRecord)
        )

        assert len(first) == 1
        assert second == []
        assert audit_count == 1


def test_missing_temporal_scope_does_not_mutate_persisted_claim() -> None:
    with _session() as session:
        older, _ = save_claim(
            session,
            _claim(
                document_id="11111111-1111-1111-1111-111111111111",
                value_text="5.50%",
            ),
        )
        newer, _ = save_claim(
            session,
            _claim(
                document_id="22222222-2222-2222-2222-222222222222",
                value_text="5.25%",
            ),
        )

        created = apply_supersession_for_newer_claim(session, newer)
        session.refresh(older)
        audit_count = session.scalar(
            select(func.count()).select_from(ClaimSupersessionRecord)
        )

        assert created == []
        assert older.state == ClaimState.CANDIDATE.value
        assert audit_count == 0


def test_cross_source_claim_does_not_supersede_persisted_history() -> None:
    with _session() as session:
        older, _ = save_claim(
            session,
            _claim(
                document_id="11111111-1111-1111-1111-111111111111",
                source_id="rbi",
                value_text="5.50%",
                effective_date=date(2026, 1, 1),
            ),
        )
        newer, _ = save_claim(
            session,
            _claim(
                document_id="22222222-2222-2222-2222-222222222222",
                source_id="imf",
                value_text="5.25%",
                effective_date=date(2026, 2, 1),
            ),
        )

        created = apply_supersession_for_newer_claim(session, newer)
        session.refresh(older)
        audit_count = session.scalar(
            select(func.count()).select_from(ClaimSupersessionRecord)
        )

        assert created == []
        assert older.state == ClaimState.CANDIDATE.value
        assert audit_count == 0
