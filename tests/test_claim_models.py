from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.claims.models import ClaimState, StructuredClaim


def test_structured_claim_preserves_grounded_financial_fact() -> None:
    claim = StructuredClaim(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text="5.25%",
        value_numeric=Decimal("5.25"),
        unit="percent",
        publication_date=date(2026, 9, 12),
        effective_date=date(2026, 9, 12),
        source_id="rbi",
        source_url="https://www.rbi.org.in/",
        document_id="fe54ee01-ee8e-4331-a045-c36fb5c6c524",
        evidence_text="Policy Repo Rate : 5.25%",
        evidence_chunk_index=1,
        confidence=0.95,
    )

    assert claim.entity == "Reserve Bank of India"
    assert claim.metric == "Policy Repo Rate"
    assert claim.value_numeric == Decimal("5.25")
    assert claim.unit == "percent"
    assert claim.state is ClaimState.CANDIDATE


def test_structured_claim_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        StructuredClaim(
            entity="Reserve Bank of India",
            metric="Policy Repo Rate",
            value_text="5.25%",
            source_id="rbi",
            source_url="https://www.rbi.org.in/",
            document_id="fe54ee01-ee8e-4331-a045-c36fb5c6c524",
            evidence_text="Policy Repo Rate : 5.25%",
            evidence_chunk_index=1,
            confidence=1.2,
        )


def test_structured_claim_rejects_blank_evidence() -> None:
    with pytest.raises(ValidationError):
        StructuredClaim(
            entity="Reserve Bank of India",
            metric="Policy Repo Rate",
            value_text="5.25%",
            source_id="rbi",
            source_url="https://www.rbi.org.in/",
            document_id="fe54ee01-ee8e-4331-a045-c36fb5c6c524",
            evidence_text="   ",
            evidence_chunk_index=1,
            confidence=0.8,
        )
