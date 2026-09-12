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
