from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.storage import claim_fingerprint, save_claim
from app.storage.database import Base, ClaimRecord


def _claim(**overrides) -> StructuredClaim:
    data = {
        "entity": "Reserve Bank of India",
        "metric": "Policy Repo Rate",
        "value_text": "5.25%",
        "value_numeric": Decimal("5.25"),
        "unit": "%",
        "publication_date": date(2026, 9, 12),
        "effective_date": date(2026, 9, 12),
        "source_id": "rbi",
        "source_url": "https://www.rbi.org.in/",
        "document_id": "fe54ee01-ee8e-4331-a045-c36fb5c6c524",
        "evidence_text": "Policy Repo Rate : 5.25%",
        "evidence_chunk_index": 1,
        "confidence": 0.95,
        "state": ClaimState.CANDIDATE,
    }
    data.update(overrides)
    return StructuredClaim(**data)


def test_claim_fingerprint_ignores_state_and_confidence() -> None:
    first = _claim(confidence=0.60, state=ClaimState.CANDIDATE)
    second = _claim(confidence=0.99, state=ClaimState.VERIFIED)

    assert claim_fingerprint(first) == claim_fingerprint(second)


def test_claim_fingerprint_changes_for_different_effective_date() -> None:
    first = _claim(effective_date=date(2026, 9, 12))
    second = _claim(effective_date=date(2026, 10, 1))

    assert claim_fingerprint(first) != claim_fingerprint(second)


def test_save_claim_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first_record, first_created = save_claim(session, _claim())
        second_record, second_created = save_claim(session, _claim())

        count = session.scalar(select(func.count()).select_from(ClaimRecord))

    assert first_created is True
    assert second_created is False
    assert first_record.id == second_record.id
    assert count == 1
