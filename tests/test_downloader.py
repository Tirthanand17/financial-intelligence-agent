import pytest

from app.ingestion.downloader import _validate_redirect_target
from app.sources.registry import get_source


def test_rejects_document_redirect_to_source_homepage() -> None:
    source = get_source("rbi")

    with pytest.raises(ValueError, match="redirected the requested document to its homepage"):
        _validate_redirect_target(
            "https://website.rbi.org.in/documents/d/rbi/example",
            "https://www.rbi.org.in/",
            source,
        )


def test_allows_requested_homepage() -> None:
    source = get_source("rbi")

    _validate_redirect_target(
        "https://www.rbi.org.in/",
        "https://www.rbi.org.in/",
        source,
    )


def test_allows_document_redirect_with_non_root_target() -> None:
    source = get_source("rbi")

    _validate_redirect_target(
        "https://www.rbi.org.in/example",
        "https://m.rbi.org.in/example",
        source,
    )
