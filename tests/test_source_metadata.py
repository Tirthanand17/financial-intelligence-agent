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


def test_sebi_detail_page_standalone_date_is_extracted() -> None:
    text = (
        "Enforcement\n"
        "Appeal No. 7052 of 2026 filed by Kamal Kumar\n"
        "Sep 11, 2026\n"
        "Orders : Orders of AA under the RTI Act"
    )

    assert extract_source_publication_date("sebi", text) == date(2026, 9, 11)


def test_sebi_body_date_embedded_in_sentence_is_not_used() -> None:
    text = (
        "Enforcement\n"
        "Appeal No. 7052 of 2026 filed by Kamal Kumar\n"
        "The appeal was received on Sep 11, 2026 and reviewed later."
    )

    assert extract_source_publication_date("sebi", text) is None


def test_unknown_source_never_gets_generic_document_date() -> None:
    text = "Date : Jun 05, 2026\nPolicy Repo Rate : 5.25%"

    assert extract_source_publication_date("unknown", text) is None
