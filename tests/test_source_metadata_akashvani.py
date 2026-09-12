from datetime import date

from app.sources.metadata import extract_source_publication_date


def test_extracts_akashvani_article_publication_date() -> None:
    text = (
        "Akashvani News\n"
        "News On AIR | June 5, 2026 2:35 PM\n"
        "RBI keeps repo rate unchanged at 5.25%\n"
    )

    assert extract_source_publication_date("akashvani", text) == date(2026, 6, 5)


def test_akashvani_unlabelled_date_is_not_used_as_page_publication_date() -> None:
    text = "June 5, 2026\nRBI keeps repo rate unchanged at 5.25%"

    assert extract_source_publication_date("akashvani", text) is None
