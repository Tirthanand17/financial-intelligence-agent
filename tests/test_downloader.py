import httpx
import pytest

import app.ingestion.downloader as downloader
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


def test_retries_transient_connection_errors_then_succeeds(monkeypatch) -> None:
    attempts = 0
    expected = object()

    def fake_download_once(source_id: str, url: str):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("connection reset", request=request)
        return expected

    monkeypatch.setattr(downloader, "_download_trusted_document_once", fake_download_once)
    monkeypatch.setattr(downloader.time, "sleep", lambda _: None)

    result = downloader.download_trusted_document("ddnews", "https://ddnews.gov.in/en/example/")

    assert result is expected
    assert attempts == 3


def test_transient_connection_errors_are_bounded(monkeypatch) -> None:
    attempts = 0

    def fake_download_once(source_id: str, url: str):
        nonlocal attempts
        attempts += 1
        request = httpx.Request("GET", url)
        raise httpx.ConnectError("connection reset", request=request)

    monkeypatch.setattr(downloader, "_download_trusted_document_once", fake_download_once)
    monkeypatch.setattr(downloader.time, "sleep", lambda _: None)

    with pytest.raises(ConnectionError, match="failed after 3 transient network attempts"):
        downloader.download_trusted_document("ddnews", "https://ddnews.gov.in/en/example/")

    assert attempts == 3


def test_policy_errors_are_not_retried(monkeypatch) -> None:
    attempts = 0

    def fake_download_once(source_id: str, url: str):
        nonlocal attempts
        attempts += 1
        raise ValueError("unsafe redirect")

    monkeypatch.setattr(downloader, "_download_trusted_document_once", fake_download_once)

    with pytest.raises(ValueError, match="unsafe redirect"):
        downloader.download_trusted_document("ddnews", "https://ddnews.gov.in/en/example/")

    assert attempts == 1
