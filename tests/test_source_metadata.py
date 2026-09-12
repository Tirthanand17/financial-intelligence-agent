from datetime import date

from app.sources.metadata import extract_source_publication_date


def test_rbi_press_release_date_is_extracted() -> None:
    text = "Reserve Bank of India\nPress Releases\nDate : Jun 05, 2026\nMonetary Policy Statement"

    assert extract_source_publication_date("rbi", text) == date(2026, 6, 5)


def test_rbi_homepage_without_page_date_stays_undated() -> None:
    text = "Current Rates\nPolicy Repo Rate\n:\n5.25%\nWebsite last updated date: Aug 06, 2026"

    assert extract_source_publication_date("rbi", text) is None


def test_ddnews_article_timestamp_is_extracted() -> None:
    text = (
        "DD News\n"
        "05/06/26 | 12:23 pm | Monetary Policy Committee (MPC) | repo rate unchanged at 5.25%\n"
        "RBI keeps repo rate unchanged at 5.25%"
    )

    assert extract_source_publication_date("ddnews", text) == date(2026, 6, 5)


def test_ddnews_unrelated_site_header_date_is_not_used() -> None:
    text = "Feedback | Wednesday, August 05, 2026\nDD News\nRBI keeps repo rate unchanged at 5.25%"

    assert extract_source_publication_date("ddnews", text) is None


def test_unknown_source_never_gets_generic_document_date() -> None:
    text = "Date : Jun 05, 2026\nPolicy Repo Rate : 5.25%"

    assert extract_source_publication_date("unknown", text) is None
