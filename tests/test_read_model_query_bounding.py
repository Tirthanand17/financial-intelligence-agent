from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.change_detection as changes
import app.services.timeline as timeline
from app.storage.database import Base, ClaimRecord


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _claim(claim_id: str, *, source_id: str, value: str, when: date) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{claim_id}",
        source_id=source_id,
        source_url=f"https://example.test/{claim_id}",
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text=f"{value}%",
        value_numeric=Decimal(value),
        unit="%",
        publication_date=when,
        effective_date=None,
        evidence_text=f"Policy Repo Rate: {value}%",
        evidence_chunk_index=0,
        confidence=0.95,
        state="candidate",
        created_at=datetime(2026, 9, 18, 3, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 18, 3, 0, tzinfo=UTC),
    )


def test_timeline_sql_scope_keeps_global_facets(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim("rbi", source_id="rbi", value="5.50", when=date(2026, 9, 1)),
                _claim("sebi", source_id="sebi", value="5.25", when=date(2026, 9, 2)),
            ]
        )
        session.commit()

    monkeypatch.setattr(timeline, "get_session", lambda: Session())
    result = timeline.build_timeline_snapshot(source_id="rbi")

    assert result["summary"]["claims_in_scope"] == 1
    assert result["performance"]["source_filter_sql_pushdown"] is True
    assert result["performance"]["full_claim_history_materialized"] is False
    assert {row["source_id"] for row in result["facets"]["sources"]} == {"rbi", "sebi"}


def test_change_detection_sql_scope_preserves_global_count(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim("rbi-a", source_id="rbi", value="6.00", when=date(2026, 8, 1)),
                _claim("rbi-b", source_id="rbi", value="5.50", when=date(2026, 9, 1)),
                _claim("sebi", source_id="sebi", value="5.25", when=date(2026, 9, 2)),
            ]
        )
        session.commit()

    monkeypatch.setattr(changes, "get_session", lambda: Session())
    result = changes.build_change_detection_snapshot(source_id="rbi")

    assert result["summary"]["persisted_claims"] == 3
    assert result["summary"]["scoped_claim_rows"] == 2
    assert result["summary"]["eligible_dated_claims"] == 2
    assert result["performance"]["source_filter_sql_pushdown"] is True
    assert result["performance"]["full_claim_history_materialized"] is False
