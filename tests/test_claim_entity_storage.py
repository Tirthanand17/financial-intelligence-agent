import json
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.claims.extractor import extract_structured_claims
from app.claims.models import ClaimState, StructuredClaim
from app.claims.storage import claim_fingerprint, save_claim
from app.storage.database import Base, ClaimEntityAttributionRecord


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _manual_claim(**overrides) -> StructuredClaim:
    data = {
        "entity": "Reserve Bank of India",
        "metric": "Policy Repo Rate",
        "value_text": "5.25%",
        "value_numeric": Decimal("5.25"),
        "unit": "%",
        "effective_date": date(2026, 9, 12),
        "source_id": "imf",
        "source_url": "https://www.imf.org/example",
        "document_id": "22222222-2222-2222-2222-222222222222",
        "evidence_text": "Policy Repo Rate : 5.25%",
        "evidence_chunk_index": 0,
        "confidence": 0.95,
        "state": ClaimState.CANDIDATE,
    }
    data.update(overrides)
    return StructuredClaim(**data)


def test_extractor_carries_explicit_entity_attribution_provenance() -> None:
    claims = extract_structured_claims(
        chunks=["RBI\nEffective Date\n2026-09-12\nPolicy Repo Rate : 5.25%"],
        document_id="22222222-2222-2222-2222-222222222222",
        source_id="imf",
        source_url="https://www.imf.org/example",
        entity="International Monetary Fund",
    )

    assert len(claims) == 1
    claim = claims[0]
    assert claim.entity == "Reserve Bank of India"
    assert claim.entity_attribution_basis == "explicit_local_alias"
    assert claim.entity_source_default == "International Monetary Fund"
    assert "RBI" in claim.entity_matched_aliases
    assert claim.entity_ambiguous_candidates == ()
    assert claim.entity_evidence_text is not None
    assert "RBI" in claim.entity_evidence_text
    assert "Policy Repo Rate : 5.25%" in claim.entity_evidence_text


def test_ambiguous_attribution_provenance_preserves_candidates() -> None:
    claims = extract_structured_claims(
        chunks=["IMF and RBI\nEffective Date\n2026-09-12\nPolicy Repo Rate : 5.25%"],
        document_id="22222222-2222-2222-2222-222222222222",
        source_id="imf",
        source_url="https://www.imf.org/example",
        entity="International Monetary Fund",
    )

    claim = claims[0]
    assert claim.entity == "International Monetary Fund"
    assert claim.entity_attribution_basis == "ambiguous_local_entities_defaulted"
    assert set(claim.entity_ambiguous_candidates) == {
        "International Monetary Fund",
        "Reserve Bank of India",
    }


def test_save_claim_persists_entity_attribution_in_separate_table() -> None:
    engine = _engine()
    claim = _manual_claim(
        entity_attribution_basis="explicit_local_alias",
        entity_source_default="International Monetary Fund",
        entity_matched_aliases=("RBI",),
        entity_evidence_text="RBI\nPolicy Repo Rate : 5.25%",
    )

    with Session(engine) as session:
        record, created = save_claim(session, claim)
        attribution = session.scalar(
            select(ClaimEntityAttributionRecord).where(
                ClaimEntityAttributionRecord.claim_id == record.id
            )
        )

    assert created is True
    assert attribution is not None
    assert attribution.canonical_entity == "Reserve Bank of India"
    assert attribution.source_default_entity == "International Monetary Fund"
    assert attribution.basis == "explicit_local_alias"
    assert json.loads(attribution.matched_aliases) == ["RBI"]
    assert json.loads(attribution.ambiguous_candidates) == []
    assert "RBI" in attribution.evidence_text


def test_entity_attribution_persistence_is_idempotent() -> None:
    engine = _engine()
    claim = _manual_claim(
        entity_attribution_basis="explicit_local_alias",
        entity_source_default="International Monetary Fund",
        entity_matched_aliases=("RBI",),
        entity_evidence_text="RBI\nPolicy Repo Rate : 5.25%",
    )

    with Session(engine) as session:
        first, first_created = save_claim(session, claim)
        second, second_created = save_claim(session, claim)
        attribution_count = session.scalar(
            select(func.count()).select_from(ClaimEntityAttributionRecord)
        )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert attribution_count == 1


def test_existing_claim_can_backfill_missing_entity_attribution() -> None:
    engine = _engine()
    original = _manual_claim()
    enriched = original.model_copy(
        update={
            "entity_attribution_basis": "explicit_local_alias",
            "entity_source_default": "International Monetary Fund",
            "entity_matched_aliases": ("RBI",),
            "entity_evidence_text": "RBI\nPolicy Repo Rate : 5.25%",
        }
    )

    assert claim_fingerprint(original) == claim_fingerprint(enriched)

    with Session(engine) as session:
        record, created = save_claim(session, original)
        assert created is True
        assert session.scalar(select(func.count()).select_from(ClaimEntityAttributionRecord)) == 0

        repeated, repeated_created = save_claim(session, enriched)
        attribution = session.scalar(
            select(ClaimEntityAttributionRecord).where(
                ClaimEntityAttributionRecord.claim_id == record.id
            )
        )

    assert repeated_created is False
    assert repeated.id == record.id
    assert attribution is not None
    assert attribution.basis == "explicit_local_alias"


def test_unspecified_manual_claim_does_not_invent_attribution_audit() -> None:
    engine = _engine()

    with Session(engine) as session:
        save_claim(session, _manual_claim())
        attribution_count = session.scalar(
            select(func.count()).select_from(ClaimEntityAttributionRecord)
        )

    assert attribution_count == 0
