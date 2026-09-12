import pytest

from app.ingestion.extractor import ExtractedDocument
from app.ingestion.quality import validate_extracted_document


def test_rejects_rbi_human_challenge_html() -> None:
    document = ExtractedDocument(
        title=None,
        text=(
            "This question is for testing whether you are a human visitor and to prevent "
            "automated spam submission. What code is in the image? Your support ID is: 12345."
        ),
    )

    with pytest.raises(ValueError, match="anti-bot/challenge page"):
        validate_extracted_document(document, "text/html")


def test_allows_normal_financial_html() -> None:
    document = ExtractedDocument(
        title="Policy document",
        text=(
            "The Reserve Bank publishes regulatory guidance to support financial stability, "
            "sound banking practices, and responsible conduct by regulated entities."
        ),
    )

    validate_extracted_document(document, "text/html")


def test_does_not_apply_html_challenge_gate_to_pdf() -> None:
    document = ExtractedDocument(
        title="Example PDF",
        text="This question is for testing whether you are a human visitor.",
    )

    validate_extracted_document(document, "application/pdf")
