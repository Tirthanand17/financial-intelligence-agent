from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.models import ClaimState, StructuredClaim
from app.claims.storage import save_claim
from app.claims.trust import assess_trust
from app.claims.trust_storage import reconcile_trust_for_claim
from app.claims.verification import assess_claim
from app.storage.database import Base, ClaimRecord, ClaimTrustEventRecord


SCOPE_DATE = date(2026, 9, 12)
NOISY_EVIDENCE = "Applications between 9:30 am and 10:30 am are accepted."


def _claim(
    *,
    source_id: str,
    entity: str,
    document_id: str,
    state: ClaimState = ClaimState.CANDIDATE,
    attribution_basis: str = "source_default",
    source_default_entity: str | None = None,
    evidence_text: str = "Policy Repo Rate : 5.25%",
) -> StructuredClaim:
    return StructuredClaim(
        entity=entity,
        metric="Policy Repo Rate",
        value_text="5.25%",
        value_numeric=Decimal("5.25"),
        unit="%",
        effective_date=SCOPE_DATE,
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        document_id=document_id,
        evidence_text=evidence_text,
        evidence_chunk_index=0,
        entity_attribution_basis=attribution_basis,
        entity_source_default=source_default_entity,
        entity_matched_aliases=("RBI",) if attribution_basis == "explicit_local_alias" else (),
        entity_evidence_text="RBI\nPolicy Repo Rate : 5.25%",
        confidence=0.95,
        state=state,
    )


def _primary(*, state: ClaimState = ClaimState.VERIFIED, evidence_text: str = "Policy Repo Rate : 5.25%") -> StructuredClaim:
    return _claim(
        source_id="rbi",
        entity="Reserve Bank of India",
        document_id="11111111-1111-1111-1111-111111111111",
        state=state,
        attribution_basis="source_default",
        source_default_entity="Reserve Bank of India",
        evidence_text=evidence_text,
    )


def _secondary(*, state: ClaimState = ClaimState.VERIFIED, evidence_text: str = "Policy Repo Rate : 5.25%") -> StructuredClaim:
    return _claim(
        source_id="imf",
        entity="Reserve Bank of India",
        document_id="22222222-2222-2222-2222-222222222222",
        state=state,
        attribution_basis="explicit_local_alias",
        source_default_entity="International Monetary Fund",
        evidence_text=evidence_text,
    )


def test_quality_failed_independent_claim_cannot_verify_clean_target() -> None:
    target = _primary(state=ClaimState.CANDIDATE)
    noisy = _secondary(state=ClaimState.CANDIDATE, evidence_text=NOISY_EVIDENCE)

    decision = assess_claim(target, [target, noisy])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "insufficient_independent_sources"
    assert decision.supporting_source_ids == ("rbi",)


def test_quality_failed_verified_target_cannot_be_trusted() -> None:
    target = _primary(evidence_text=NOISY_EVIDENCE)
    corroborator = _secondary()

    decision = assess_trust(target, [target, corroborator])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "quality_gate_failed"
    assert decision.corroborating_source_ids == ()


def test_quality_failed_corroborator_cannot_promote_clean_primary() -> None:
    target = _primary()
    noisy = _secondary(evidence_text=NOISY_EVIDENCE)

    decision = assess_trust(target, [target, noisy])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "insufficient_qualified_corroboration"
    assert decision.corroborating_source_ids == ()


def test_persisted_quality_failed_corroborator_creates_no_trust_event() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        primary_record, _ = save_claim(session, _primary())
        save_claim(session, _secondary(evidence_text=NOISY_EVIDENCE))

        events = reconcile_trust_for_claim(session, primary_record)
        state = session.scalar(
            select(ClaimRecord.state).where(ClaimRecord.id == primary_record.id)
        )
        event_count = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        )

    assert events == []
    assert state == ClaimState.VERIFIED.value
    assert event_count == 0
