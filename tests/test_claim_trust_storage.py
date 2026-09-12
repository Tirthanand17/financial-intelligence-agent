import json
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.storage import save_claim
from app.claims.trust_storage import reconcile_trust_for_claim
from app.storage.database import Base, ClaimRecord, ClaimTrustEventRecord


EFFECTIVE_DATE = date(2026, 9, 12)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _claim(
    *,
    source_id: str,
    entity: str,
    document_id: str,
    value_text: str = "5.25%",
    state: ClaimState = ClaimState.VERIFIED,
    attribution_basis: str = "source_default",
    source_default_entity: str | None,
    matched_aliases: tuple[str, ...] = (),
    effective_date: date | None = EFFECTIVE_DATE,
) -> StructuredClaim:
    return StructuredClaim(
        entity=entity,
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
        entity_attribution_basis=attribution_basis,
        entity_source_default=source_default_entity,
        entity_matched_aliases=matched_aliases,
        entity_evidence_text=f"RBI\nPolicy Repo Rate : {value_text}",
        confidence=0.95,
        state=state,
    )


def _primary(**overrides) -> StructuredClaim:
    data = {
        "source_id": "rbi",
        "entity": "Reserve Bank of India",
        "document_id": "11111111-1111-1111-1111-111111111111",
        "source_default_entity": "Reserve Bank of India",
        "attribution_basis": "source_default",
    }
    data.update(overrides)
    return _claim(**data)


def _secondary(**overrides) -> StructuredClaim:
    data = {
        "source_id": "imf",
        "entity": "Reserve Bank of India",
        "document_id": "22222222-2222-2222-2222-222222222222",
        "source_default_entity": "International Monetary Fund",
        "attribution_basis": "explicit_local_alias",
        "matched_aliases": ("RBI",),
    }
    data.update(overrides)
    return _claim(**data)


def test_qualified_primary_is_promoted_and_audited() -> None:
    engine = _engine()

    with Session(engine) as session:
        primary_record, _ = save_claim(session, _primary())
        secondary_record, _ = save_claim(session, _secondary())

        events = reconcile_trust_for_claim(session, primary_record)

        primary_state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == primary_record.id)
        )
        secondary_state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == secondary_record.id)
        )
        stored_events = list(session.scalars(select(ClaimTrustEventRecord)))

    assert primary_state == "trusted"
    assert secondary_state == "verified"
    assert len(events) == 1
    assert len(stored_events) == 1
    assert stored_events[0].claim_id == primary_record.id
    assert stored_events[0].from_state == "verified"
    assert stored_events[0].to_state == "trusted"
    assert stored_events[0].reason == "verified_primary_with_independent_authoritative_corroboration"
    assert json.loads(stored_events[0].corroborating_source_ids) == ["imf"]


def test_repeated_trust_reconciliation_is_idempotent() -> None:
    engine = _engine()

    with Session(engine) as session:
        primary_record, _ = save_claim(session, _primary())
        save_claim(session, _secondary())

        first = reconcile_trust_for_claim(session, primary_record)
        repeated = reconcile_trust_for_claim(session, primary_record)
        event_count = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        )

    assert len(first) == 1
    assert repeated == []
    assert event_count == 1


def test_missing_primary_attribution_blocks_persisted_promotion() -> None:
    engine = _engine()

    with Session(engine) as session:
        primary_record, _ = save_claim(
            session,
            _primary(
                attribution_basis="unspecified",
                source_default_entity=None,
            ),
        )
        save_claim(session, _secondary())

        events = reconcile_trust_for_claim(session, primary_record)
        state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == primary_record.id)
        )

    assert events == []
    assert state == "verified"


def test_ambiguous_secondary_attribution_does_not_promote_primary() -> None:
    engine = _engine()

    with Session(engine) as session:
        primary_record, _ = save_claim(session, _primary())
        save_claim(
            session,
            _secondary(
                attribution_basis="ambiguous_local_entities_defaulted",
                matched_aliases=(),
            ),
        )

        events = reconcile_trust_for_claim(session, primary_record)
        state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == primary_record.id)
        )

    assert events == []
    assert state == "verified"


def test_conflicting_comparable_value_blocks_persisted_promotion() -> None:
    engine = _engine()

    with Session(engine) as session:
        primary_record, _ = save_claim(session, _primary())
        save_claim(session, _secondary())
        save_claim(
            session,
            _claim(
                source_id="world_bank",
                entity="Reserve Bank of India",
                document_id="33333333-3333-3333-3333-333333333333",
                value_text="5.50%",
                source_default_entity="World Bank",
                attribution_basis="explicit_local_alias",
                matched_aliases=("RBI",),
            ),
        )

        events = reconcile_trust_for_claim(session, primary_record)
        state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == primary_record.id)
        )
        event_count = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        )

    assert events == []
    assert state == "verified"
    assert event_count == 0


def test_missing_temporal_scope_blocks_persisted_promotion() -> None:
    engine = _engine()

    with Session(engine) as session:
        primary_record, _ = save_claim(session, _primary(effective_date=None))
        save_claim(session, _secondary(effective_date=None))

        events = reconcile_trust_for_claim(session, primary_record)
        state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == primary_record.id)
        )

    assert events == []
    assert state == "verified"


def test_secondary_claim_is_never_promoted_as_direct_primary_target() -> None:
    engine = _engine()

    with Session(engine) as session:
        primary_record, _ = save_claim(session, _primary())
        secondary_record, _ = save_claim(session, _secondary())

        events = reconcile_trust_for_claim(session, secondary_record)
        primary_state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == primary_record.id)
        )
        secondary_state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == secondary_record.id)
        )

    assert events == []
    assert primary_state == "verified"
    assert secondary_state == "verified"
