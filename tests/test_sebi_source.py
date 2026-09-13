import pytest

from app.sources.sebi import extract_sebi_primary_pdf_url


PAGE_URL = "https://www.sebi.gov.in/enforcement/orders/sep-2026/example.html"


def test_extracts_direct_first_party_sebi_pdf_attachment() -> None:
    content = b"""<html><body>
    <a href="/sebi_data/attachdocs/sep-2026/order.pdf">Order PDF</a>
    </body></html>"""

    assert extract_sebi_primary_pdf_url(content, PAGE_URL) == (
        "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/order.pdf"
    )


def test_extracts_pdf_from_official_sebi_viewer_wrapper() -> None:
    content = b"""<html><body>
    <a href="/web/?file=https%3A%2F%2Fwww.sebi.gov.in%2Fsebi_data%2Fattachdocs%2Fsep-2026%2Forder.pdf">Order PDF</a>
    </body></html>"""

    assert extract_sebi_primary_pdf_url(content, PAGE_URL) == (
        "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/order.pdf"
    )


def test_extracts_viewer_target_from_onclick_without_executing_javascript() -> None:
    content = b"""<html><body>
    <a href="#" onclick="window.open('/web/?file=https%3A%2F%2Fwww.sebi.gov.in%2Fsebi_data%2Fattachdocs%2Fsep-2026%2Forder.pdf','_blank')">Order PDF</a>
    </body></html>"""

    assert extract_sebi_primary_pdf_url(content, PAGE_URL) == (
        "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/order.pdf"
    )


def test_extracts_direct_pdf_from_data_url_attribute() -> None:
    content = b"""<html><body>
    <button data-url="https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/order.pdf">Open</button>
    </body></html>"""

    assert extract_sebi_primary_pdf_url(content, PAGE_URL) == (
        "https://www.sebi.gov.in/sebi_data/attachdocs/sep-2026/order.pdf"
    )


def test_cross_host_or_non_attachment_links_are_not_candidates() -> None:
    content = b"""<html><body>
    <a href="https://example.com/sebi_data/attachdocs/order.pdf">External</a>
    <a href="https://www.sebi.gov.in/about.html">About</a>
    <button onclick="window.open('https://example.com/sebi_data/attachdocs/order.pdf')">External JS</button>
    </body></html>"""

    assert extract_sebi_primary_pdf_url(content, PAGE_URL) is None


def test_multiple_distinct_approved_pdf_attachments_fail_closed() -> None:
    content = b"""<html><body>
    <a href="/sebi_data/attachdocs/sep-2026/one.pdf">One</a>
    <button data-url="/sebi_data/attachdocs/sep-2026/two.pdf">Two</button>
    </body></html>"""

    with pytest.raises(ValueError, match="multiple approved PDF attachments"):
        extract_sebi_primary_pdf_url(content, PAGE_URL)
