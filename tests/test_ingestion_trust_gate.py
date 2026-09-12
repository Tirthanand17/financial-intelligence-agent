from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.services.ingestion import _stage_claims
from app.storage.database import Base, ClaimRecord, ClaimTrustEventRecord


def _claim(
    *,
    source_id: str,
    source_url: str,
    document_id: str,
    attribution_basis: str,
) -> StructuredClaim:
    return StructuredClaim(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text="5.25%",
        value_numeric=Decimal("5.25"),
        unit="%",
        publication_date=date(2026, 6, 5),
        effective_date=None,
        source_id=source_id,
        source_url=source_url,
        document_id=document_id,
        evidence_text="RBI Policy Repo Rate : 5.25%",
        evidence_chunk_index=0,
        entity_attribution_basis=attribution_basis,
        entity_source_default=(
            "Reserve Bank of India" if source_id == "rbi" else "DD News"
        ),
        entity_matched_aliases=("RBI",) if attribution_basis == "explicit_local_alias" else (),
        entity_evidence_text="RBI Policy Repo Rate : 5.25%",
        confidence=0.95,
        state=ClaimState.CANDIDATE,
    )


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_trust_promotion_stays_off_when_safety_gate_is_disabled() -> None:
    engine = _engine()
    primary = _claim(
        source_id="rbi",
        source_url="https://www.rbi.org.in/example-primary",
        document_id="11111111-1111-1111-1111-111111111111",
        attribution_basis="source_default",
    )
    secondary = _claim(
        source_id="ddnews",
        source_url="https://ddnews.gov.in/en/example-secondary/",
        document_id="22222222-2222-2222-2222-222222222222",
        attribution_basis="explicit_local_alias",
    )

    with Session(engine) as session:
        first = _stage_claims(session, [primary], trust_promotion_enabled=False)
        second = _stage_claims(session, [secondary], trust_promotion_enabled=False)
        session.commit()

        states = {
            record.source_id: record.state
            for record in session.scalars(select(ClaimRecord)).all()
        }
        trust_event_count = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        )

    assert first[3] == 0
    assert second[2] == 2
    assert second[3] == 0
    assert states == {"rbi": "verified", "ddnews": "verified"}
    assert trust_event_count == 0


def test_enabled_gate_revisits_primary_when_secondary_arrives() -> None:
    engine = _engine()
    primary = _claim(
        source_id="rbi",
        source_url="https://www.rbi.org.in/example-primary",
        document_id="11111111-1111-1111-1111-111111111111",
        attribution_basis="source_default",
    )
    secondary = _claim(
        source_id="ddnews",
        source_url="https://ddnews.gov.in/en/example-secondary/",
        document_id="22222222-2222-2222-2222-222222222222",
        attribution_basis="explicit_local_alias",
    )

    with Session(engine) as session:
        first = _stage_claims(session, [primary], trust_promotion_enabled=True)
        second = _stage_claims(session, [secondary], trust_promotion_enabled=True)
        session.commit()

        states = {
            record.source_id: record.state
            for record in session.scalars(select(ClaimRecord)).all()
        }
        trust_events = list(session.scalars(select(ClaimTrustEventRecord)))

    assert first[3] == 0
    assert second[2] == 2
    assert second[3] == 1
    assert states == {"rbi": "trusted", "ddnews": "verified"}
    assert len(trust_events) == 1
    assert trust_events[0].from_state == "verified"
    assert trust_events[0].to_state == "trusted"
    assert trust_events[0].reason == (
        "verified_primary_with_independent_authoritative_corroboration"
    )


def test_enabled_gate_is_idempotent_after_primary_is_trusted() -> None:
    engine = _engine()
    primary = _claim(
        source_id="rbi",
        source_url="https://www.rbi.org.in/example-primary",
        document_id="11111111-1111-1111-1111-111111111111",
        attribution_basis="source_default",
    )
    secondary = _claim(
        source_id="ddnews",
        source_url="https://ddnews.gov.in/en/example-secondary/",
        document_id="22222222-2222-2222-2222-222222222222",
        attribution_basis="explicit_local_alias",
    )

    with Session(engine) as session:
        _stage_claims(session, [primary], trust_promotion_enabled=True)
        _stage_claims(session, [secondary], trust_promotion_enabled=True)
        repeated = _stage_claims(session, [secondary], trust_promotion_enabled=True)
        session.commit()

        trust_event_count = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        )

    assert repeated[3] == 0
    assert trust_event_count == 1
