from datetime import UTC, datetime
from hashlib import sha256

import pymupdf
import pytest

from app.ingestion.downloader import DownloadedDocument
from app.monitoring.preflight import preflight_discovered_url
from app.sources.registry import get_source


CHUNK_SIZE = 3500
CHUNK_OVERLAP = 400
WRAPPER_URL = "https://www.sebi.gov.in/enforcement/orders/sep-2026/appeal-no-7052.html"
PDF_URL = "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/appeal-7052.pdf"


def _pdf_bytes(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def _downloaded(url: str, content: bytes, content_type: str) -> DownloadedDocument:
    source = get_source("sebi")
    return DownloadedDocument(
        source=source,
        source_url=url,
        final_url=url,
        content=content,
        content_type=content_type,
        sha256=sha256(content).hexdigest(),
        retrieved_at=datetime(2026, 9, 13, 2, 0, tzinfo=UTC),
    )


def test_sebi_wrapper_resolves_one_pdf_and_keeps_wrapper_date_provenance() -> None:
    wrapper = b"""<html><head><title>SEBI order</title></head><body>
    <h1>Appeal No. 7052 of 2026 filed by Kamal Kumar</h1>
    <h5>Sep 11, 2026</h5>
    <p>Orders : Orders of AA under the RTI Act</p>
    <a href="/web/?file=https%3A%2F%2Fwww.sebi.gov.in%2Fsebi_data%2Fattachdocs%2Fsep-2026%2Fappeal-7052.pdf">Order PDF</a>
    </body></html>"""
    pdf = _pdf_bytes(
        "Securities and Exchange Board of India\nAppeal No. 7052 of 2026\nThis is the authoritative attached order."
    )
    calls: list[str] = []

    def download(source_id: str, url: str) -> DownloadedDocument:
        assert source_id == "sebi"
        calls.append(url)
        if url == WRAPPER_URL:
            return _downloaded(url, wrapper, "text/html")
        if url == PDF_URL:
            return _downloaded(url, pdf, "application/pdf")
        raise AssertionError(f"unexpected URL: {url}")

    result = preflight_discovered_url(
        "sebi",
        WRAPPER_URL,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        download=download,
    )

    assert calls == [WRAPPER_URL, PDF_URL]
    assert result.requested_url == WRAPPER_URL
    assert result.final_url == PDF_URL
    assert result.content_type == "application/pdf"
    assert result.downloaded.content == pdf
    assert result.downloaded.source_url == WRAPPER_URL
    assert result.downloaded.final_url == PDF_URL
    assert result.publication_date is not None
    assert result.publication_date.isoformat() == "2026-09-11"
    assert result.downloaded.publication_date_hint == result.publication_date
    assert result.text_chars > 0
    assert result.chunk_count == 1


def test_thin_sebi_wrapper_without_approved_pdf_is_rejected() -> None:
    wrapper = b"""<html><body>
    <h1>Appeal No. 7052 of 2026 filed by Kamal Kumar</h1>
    <h5>Sep 11, 2026</h5>
    <p>Orders : Orders of AA under the RTI Act</p>
    </body></html>"""

    with pytest.raises(ValueError, match="thin HTML wrapper"):
        preflight_discovered_url(
            "sebi",
            WRAPPER_URL,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            download=lambda *_: _downloaded(WRAPPER_URL, wrapper, "text/html"),
        )


def test_sebi_wrapper_never_follows_cross_host_pdf() -> None:
    wrapper = b"""<html><body>
    <h1>SEBI order</h1>
    <h5>Sep 11, 2026</h5>
    <a href="https://example.com/sebi_data/attachdocs/order.pdf">External PDF</a>
    </body></html>"""
    calls = 0

    def download(source_id: str, url: str) -> DownloadedDocument:
        nonlocal calls
        calls += 1
        assert url == WRAPPER_URL
        return _downloaded(url, wrapper, "text/html")

    with pytest.raises(ValueError, match="thin HTML wrapper"):
        preflight_discovered_url(
            "sebi",
            WRAPPER_URL,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            download=download,
        )

    assert calls == 1
