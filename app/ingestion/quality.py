from app.ingestion.extractor import ExtractedDocument


# Strong phrases commonly returned by web application firewalls/challenge pages.
# We reject these pages rather than storing them as trusted financial evidence.
STRONG_BLOCK_MARKERS: tuple[str, ...] = (
    "this question is for testing whether you are a human visitor",
    "what code is in the image?",
    "your support id is:",
    "the requested url was rejected",
)

WEAK_BLOCK_MARKERS: tuple[str, ...] = (
    "please enable javascript to view the page content",
    "audio is not supported in your browser",
    "request rejected",
    "access denied",
)


def validate_extracted_document(document: ExtractedDocument, content_type: str) -> None:
    """Reject obvious challenge/error pages before they enter trusted storage.

    The gate is deliberately conservative: it only applies challenge-page
    detection to HTML responses, while legitimate PDF/text documents continue
    through the normal ingestion path.
    """
    if content_type != "text/html":
        return

    normalized = " ".join(document.text.lower().split())

    if any(marker in normalized for marker in STRONG_BLOCK_MARKERS):
        raise ValueError(
            "Source returned an anti-bot/challenge page instead of the requested document; "
            "it was rejected and will not be indexed."
        )

    weak_hits = sum(marker in normalized for marker in WEAK_BLOCK_MARKERS)
    if weak_hits >= 2:
        raise ValueError(
            "Source returned an access/challenge page instead of trusted document content; "
            "it was rejected and will not be indexed."
        )
