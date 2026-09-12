from datetime import date
from decimal import Decimal

from app.claims.models import ClaimState, StructuredClaim
from app.claims.trust import assess_trust


def _claim(
    *,
    source_id: str,
    entity: str,
    document_id: str,
    value_text: str = "5.25%",
    effective_date: date | None = date(2026, 9, 12),
    publication_date: date | None = None,
    state: ClaimState = ClaimState.VERIFIED,
    attribution_basis: str = "source_default",
    source_default_entity: str | None = None,
) -> StructuredClaim:
    if source_default_entity is None:
        source_default_entity = {
            "rbi": "Reserve Bank of India",
            "sebi": "Securities and Exchange Board of India",
            "nse": "National Stock Exchange of India",
            "mospi": "Ministry of Statistics and Programme Implementation",
            "world_bank": "World Bank",
            "imf": "International Monetary Fund",
            "ddnews": "DD News",
        }.get(source_id)

    numeric_text = value_text.lower().replace("per cent", "").rstrip("%").strip()
    return StructuredClaim(
        entity=entity,
        metric="Policy Repo Rate",
        value_text=value_text,
        value_numeric=Decimal(numeric_text),
        unit="%",
        publication_date=publication_date,
        effective_date=effective_date,
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        document_id=document_id,
        evidence_text=f"Policy Repo Rate : {value_text}",
        evidence_chunk_index=0,
        entity_attribution_basis=attribution_basis,
        entity_source_default=source_default_entity,
        entity_matched_aliases=("RBI",) if attribution_basis == "explicit_local_alias" else (),
        entity_evidence_text=f"RBI\nPolicy Repo Rate : {value_text}",
        confidence=0.95,
        state=state,
    )


def _primary(**overrides) -> StructuredClaim:
    data = {
        "source_id": "rbi",
        "entity": "Reserve Bank of India",
        "document_id": "11111111-1111-1111-1111-111111111111",
        "attribution_basis": "source_default",
        "source_default_entity": "Reserve Bank of India",
    }
    data.update(overrides)
    return _claim(**data)


def _imf_corroborator(**overrides) -> StructuredClaim:
    data = {
        "source_id": "imf",
        "entity": "Reserve Bank of India",
        "document_id": "22222222-2222-2222-2222-222222222222",
        "attribution_basis": "explicit_local_alias",
        "source_default_entity": "International Monetary Fund",
    }
    data.update(overrides)
    return _claim(**data)


def test_verified_rbi_primary_with_qualified_imf_corroboration_becomes_trusted() -> None:
    primary = _primary()
    secondary = _imf_corroborator()

    decision = assess_trust(primary, [primary, secondary])

    assert decision.state is ClaimState.TRUSTED
    assert decision.reason == "verified_primary_with_independent_authoritative_corroboration"
    assert decision.corroborating_source_ids == ("imf",)


def test_verified_rbi_primary_accepts_equivalent_ddnews_percent_wording() -> None:
    primary = _primary(
        effective_date=None,
        publication_date=date(2026, 6, 5),
    )
    secondary = _claim(
        source_id="ddnews",
        entity="Reserve Bank of India",
        document_id="77777777-7777-7777-7777-777777777777",
        value_text="5.25 per cent",
        effective_date=None,
        publication_date=date(2026, 6, 5),
        attribution_basis="explicit_local_alias",
        source_default_entity="DD News",
    )

    decision = assess_trust(primary, [primary, secondary])

    assert decision.state is ClaimState.TRUSTED
    assert decision.corroborating_source_ids == ("ddnews",)


def test_candidate_target_cannot_skip_verification() -> None:
    primary = _primary(state=ClaimState.CANDIDATE)
    secondary = _imf_corroborator()

    decision = assess_trust(primary, [primary, secondary])

    assert decision.state is ClaimState.CANDIDATE
    assert decision.reason == "target_not_verified"


def test_verified_claim_without_temporal_scope_is_not_trusted() -> None:
    primary = _primary(effective_date=None)
    secondary = _imf_corroborator(effective_date=None)

    decision = assess_trust(primary, [primary, secondary])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "missing_temporal_scope"


def test_authority_b_source_cannot_be_automatic_primary_trusted_claim() -> None:
    target = _claim(
        source_id="world_bank",
        entity="World Bank",
        document_id="33333333-3333-3333-3333-333333333333",
        attribution_basis="source_default",
        source_default_entity="World Bank",
    )
    corroborator = _claim(
        source_id="imf",
        entity="World Bank",
        document_id="44444444-4444-4444-4444-444444444444",
        attribution_basis="explicit_local_alias",
        source_default_entity="International Monetary Fund",
    )

    decision = assess_trust(target, [target, corroborator])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "target_source_not_authority_a"


def test_primary_claim_requires_auditable_entity_attribution() -> None:
    primary = _primary(
        attribution_basis="unspecified",
        source_default_entity=None,
    )
    secondary = _imf_corroborator()

    decision = assess_trust(primary, [primary, secondary])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "target_entity_attribution_not_auditable"


def test_secondary_cross_entity_claim_requires_explicit_local_alias() -> None:
    primary = _primary()
    secondary = _imf_corroborator(
        attribution_basis="ambiguous_local_entities_defaulted",
    )

    decision = assess_trust(primary, [primary, secondary])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "insufficient_qualified_corroboration"


def test_same_source_duplicate_is_not_independent_corroboration() -> None:
    primary = _primary()
    duplicate = _primary(
        document_id="55555555-5555-5555-5555-555555555555",
    )

    decision = assess_trust(primary, [primary, duplicate])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "insufficient_qualified_corroboration"


def test_active_comparable_value_disagreement_blocks_trust() -> None:
    primary = _primary()
    agreeing = _imf_corroborator()
    conflicting = _claim(
        source_id="world_bank",
        entity="Reserve Bank of India",
        document_id="66666666-6666-6666-6666-666666666666",
        value_text="5.50%",
        attribution_basis="explicit_local_alias",
        source_default_entity="World Bank",
    )

    decision = assess_trust(primary, [primary, agreeing, conflicting])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "active_comparable_value_conflict"


def test_different_temporal_scope_does_not_corroborate_target() -> None:
    primary = _primary()
    secondary = _imf_corroborator(effective_date=date(2026, 8, 1))

    decision = assess_trust(primary, [primary, secondary])

    assert decision.state is ClaimState.VERIFIED
    assert decision.reason == "insufficient_qualified_corroboration"


def test_trusted_target_is_preserved_without_repromotion() -> None:
    primary = _primary(state=ClaimState.TRUSTED)

    decision = assess_trust(primary, [primary])

    assert decision.state is ClaimState.TRUSTED
    assert decision.reason == "already_trusted"
