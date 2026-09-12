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

    monkeypatch.setattr(qa, "search_chunks", lambda *args, **kwargs: matches)

    result = qa.answer_question("What changed in monetary policy?", source_id="rbi")

    assert result["confidence"] == "low"
    assert result["confidence_basis"] == "weak_semantic_retrieval"
