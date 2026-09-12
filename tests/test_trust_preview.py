from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.storage import save_claim
from app.claims.trust_storage import assess_persisted_trust
from app.storage.database import Base, ClaimRecord, ClaimTrustEventRecord


def _claim(
    *,
    source_id: str,
    source_url: str,
    document_id: str,
    source_default: str,
    attribution_basis: str,
) -> StructuredClaim:
    return StructuredClaim(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text="5.25%",
        value_numeric=Decimal("5.25"),
        unit="%",
        publication_date=date(2026, 6, 5),
        source_id=source_id,
        source_url=source_url,
        document_id=document_id,
        evidence_text="RBI Policy Repo Rate : 5.25%",
        evidence_chunk_index=0,
        entity_attribution_basis=attribution_basis,
        entity_source_default=source_default,
        entity_matched_aliases=("RBI",) if attribution_basis == "explicit_local_alias" else (),
        entity_evidence_text="RBI Policy Repo Rate : 5.25%",
        confidence=0.95,
        state=ClaimState.VERIFIED,
    )


def test_persisted_trust_preview_is_read_only() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    primary = _claim(
        source_id="rbi",
        source_url="https://www.rbi.org.in/example-primary",
        document_id="11111111-1111-1111-1111-111111111111",
        source_default="Reserve Bank of India",
        attribution_basis="source_default",
    )
    secondary = _claim(
        source_id="ddnews",
        source_url="https://ddnews.gov.in/en/example-secondary/",
        document_id="22222222-2222-2222-2222-222222222222",
        source_default="DD News",
        attribution_basis="explicit_local_alias",
    )

    with Session(engine) as session:
        primary_record, _ = save_claim(session, primary)
        save_claim(session, secondary)

        decision = assess_persisted_trust(session, primary_record)

        states = {
            record.source_id: record.state
            for record in session.scalars(select(ClaimRecord)).all()
        }
        event_count = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        )

    assert decision.state is ClaimState.TRUSTED
    assert decision.reason == (
        "verified_primary_with_independent_authoritative_corroboration"
    )
    assert decision.corroborating_source_ids == ("ddnews",)
    assert states == {"rbi": "verified", "ddnews": "verified"}
    assert event_count == 0
