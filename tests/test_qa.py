from app.claims.query import StructuredClaimResolution
from app.services import qa
from app.services.qa import _extractive_answer


def test_extractive_answer_prefers_exact_repo_rate_value() -> None:
    matches = [
        {
            "score": 0.31,
            "text": (
                "Home Reserve Bank of India Current Rates Policy Rates "
                "Policy Repo Rate : 5.25% Standing Deposit Facility Rate : 5.00% "
                "Marginal Standing Facility Rate : 5.50%"
            ),
        }
    ]

    answer = _extractive_answer(
        "What policy repo rate is shown on the RBI website?",
        matches,
    )

    assert answer == "Policy Repo Rate : 5.25% [1]"


def test_extractive_answer_uses_relevant_structured_metric() -> None:
    matches = [
        {
            "score": 0.42,
            "text": "Reserve Ratios CRR : 3.00% SLR : 18.00%",
        }
    ]

    answer = _extractive_answer("What is the CRR?", matches)

    assert answer == "CRR : 3.00% [1]"


def test_extractive_answer_still_handles_non_numeric_questions() -> None:
    matches = [
        {
            "score": 0.61,
            "text": "The handbook explains the regulatory framework and organizes applicable requirements for regulated entities.",
        }
    ]

    answer = _extractive_answer("What does the handbook explain?", matches)

    assert "regulatory framework" in answer


def test_answer_question_rates_exact_official_structured_fact_high_confidence(monkeypatch) -> None:
    matches = [
        {
            "score": 0.31,
            "source_id": "rbi",
            "source_name": "Reserve Bank of India",
            "title": "Home | Official website of Reserve Bank of India",
            "source_url": "https://www.rbi.org.in/",
            "retrieved_at": "2026-09-12T00:00:00+00:00",
            "authority_level": "A",
            "chunk_index": 0,
            "text": "Current Rates Policy Rates Policy Repo Rate : 5.25% Standing Deposit Facility Rate : 5.00%",
        }
    ]

    monkeypatch.setattr(qa, "_structured_claim_resolution", lambda *args, **kwargs: None)
    monkeypatch.setattr(qa, "search_chunks", lambda *args, **kwargs: matches)

    result = qa.answer_question(
        "What policy repo rate is shown on the RBI website?",
        source_id="rbi",
    )

    assert result["answer"] == "Policy Repo Rate : 5.25% [1]"
    assert result["confidence"] == "high"
    assert result["confidence_basis"] == "exact_structured_fact_from_high_authority_source"


def test_answer_question_does_not_overstate_weak_unstructured_evidence(monkeypatch) -> None:
    matches = [
        {
            "score": 0.22,
            "source_id": "rbi",
            "authority_level": "A",
            "text": "A general navigation item mentions monetary policy without answering the question.",
        }
    ]

    monkeypatch.setattr(qa, "_structured_claim_resolution", lambda *args, **kwargs: None)
    monkeypatch.setattr(qa, "search_chunks", lambda *args, **kwargs: matches)

    result = qa.answer_question("What changed in monetary policy?", source_id="rbi")

    assert result["confidence"] == "low"
    assert result["confidence_basis"] == "weak_semantic_retrieval"


def test_answer_question_prefers_verified_structured_claim_without_vector_search(monkeypatch) -> None:
    resolution = StructuredClaimResolution(
        status="answer",
        answer="Policy Repo Rate : 5.25%",
        confidence="high",
        confidence_basis="verified_structured_claim",
        evidence=(
            {
                "source_id": "rbi",
                "source_url": "https://www.rbi.org.in/",
                "metric": "Policy Repo Rate",
                "value": "5.25%",
                "state": "verified",
            },
        ),
    )
    monkeypatch.setattr(qa, "_structured_claim_resolution", lambda *args, **kwargs: resolution)

    def _unexpected_vector_search(*args, **kwargs):
        raise AssertionError("vector search should not run when structured claims resolve the question")

    monkeypatch.setattr(qa, "search_chunks", _unexpected_vector_search)

    result = qa.answer_question("What is the policy repo rate?", source_id="rbi")

    assert result["answer_mode"] == "structured_claim_grounded"
    assert result["answer"] == "Policy Repo Rate : 5.25%"
    assert result["confidence_basis"] == "verified_structured_claim"


def test_answer_question_surfaces_structured_conflict_instead_of_guessing(monkeypatch) -> None:
    resolution = StructuredClaimResolution(
        status="conflict",
        answer="Conflicting structured claims exist for Policy Repo Rate; no single value is presented as current fact.",
        confidence="low",
        confidence_basis="conflicting_structured_claims",
        evidence=(
            {"source_id": "rbi", "value": "5.25%", "state": "conflicted"},
            {"source_id": "imf", "value": "5.50%", "state": "conflicted"},
        ),
    )
    monkeypatch.setattr(qa, "_structured_claim_resolution", lambda *args, **kwargs: resolution)

    def _unexpected_vector_search(*args, **kwargs):
        raise AssertionError("vector search should not bypass a structured conflict")

    monkeypatch.setattr(qa, "search_chunks", _unexpected_vector_search)

    result = qa.answer_question("What is the policy repo rate?")

    assert result["answer_mode"] == "structured_claim_conflict"
    assert result["confidence"] == "low"
    assert result["confidence_basis"] == "conflicting_structured_claims"
