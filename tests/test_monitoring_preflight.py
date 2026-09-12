from datetime import UTC, datetime
from hashlib import sha256

import pytest

from app.ingestion.downloader import DownloadedDocument
from app.monitoring.preflight import preflight_discovered_url
from app.sources.registry import get_source


CHUNK_SIZE = 3500
CHUNK_OVERLAP = 400


def _downloaded(*, content: bytes, content_type: str = "text/html") -> DownloadedDocument:
    source = get_source("rbi")
    url = "https://www.rbi.org.in/press-release/123"
    return DownloadedDocument(
        source=source,
        source_url=url,
        final_url=url,
        content=content,
        content_type=content_type,
        sha256=sha256(content).hexdigest(),
        retrieved_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
    )


def test_preflight_runs_normal_extraction_without_persistence() -> None:
    content = b"""<html><head><title>RBI release</title></head><body>
    <h1>Reserve Bank of India</h1>
    <p>Date : Sep 11, 2026</p>
    <p>Policy Repo Rate : 5.25%</p>
    </body></html>"""

    calls = 0

    def download(source_id: str, url: str):
        nonlocal calls
        calls += 1
        assert source_id == "rbi"
        return _downloaded(content=content)

    result = preflight_discovered_url(
        "rbi",
        "https://www.rbi.org.in/press-release/123",
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        download=download,
    )

    assert calls == 1
    assert result.source_id == "rbi"
    assert result.title == "RBI release"
    assert result.content_bytes == len(content)
    assert result.text_chars > 0
    assert result.chunk_count >= 1
    assert result.publication_date is not None
    assert result.publication_date.isoformat() == "2026-09-11"
    assert result.eligible_claim_count >= 1


def test_preflight_rejects_challenge_page() -> None:
    content = b"""<html><body>
    This question is for testing whether you are a human visitor.
    What code is in the image?
    </body></html>"""

    with pytest.raises(ValueError, match="anti-bot/challenge"):
        preflight_discovered_url(
            "rbi",
            "https://www.rbi.org.in/press-release/123",
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            download=lambda *_: _downloaded(content=content),
        )


def test_preflight_rejects_non_allowlisted_url_before_download() -> None:
    calls = 0

    def download(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("download must not run")

    with pytest.raises(ValueError):
        preflight_discovered_url(
            "rbi",
            "https://example.com/not-rbi",
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            download=download,
        )

    assert calls == 0


def test_preflight_rejects_empty_extracted_document() -> None:
    # script/style/noscript/svg nodes are deliberately removed by the normal HTML
    # extractor, leaving no user-visible evidence text at all.
    content = b"<html><body><script>ignored</script><style>.x{}</style></body></html>"

    with pytest.raises(ValueError, match="No extractable text"):
        preflight_discovered_url(
            "rbi",
            "https://www.rbi.org.in/press-release/123",
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            download=lambda *_: _downloaded(content=content),
        )


def test_preflight_rejects_invalid_chunk_configuration_before_download() -> None:
    calls = 0

    def download(source_id: str, url: str):
        nonlocal calls
        calls += 1
        raise AssertionError("download must not run")

    with pytest.raises(ValueError, match="chunk_overlap"):
        preflight_discovered_url(
            "rbi",
            "https://www.rbi.org.in/press-release/123",
            chunk_size=100,
            chunk_overlap=100,
            download=download,
        )

    assert calls == 0
