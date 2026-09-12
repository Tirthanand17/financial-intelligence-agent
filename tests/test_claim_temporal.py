from datetime import date

from app.claims.temporal import extract_temporal_metadata


def test_extracts_effective_date_from_text() -> None:
    metadata = extract_temporal_metadata("Policy rate effective from 12 September 2026")

    assert metadata.effective_date == date(2026, 9, 12)
    assert metadata.publication_date is None


def test_extracts_publication_date_from_text() -> None:
    metadata = extract_temporal_metadata("Published on September 12, 2026")

    assert metadata.publication_date == date(2026, 9, 12)
    assert metadata.effective_date is None


def test_extracts_numeric_effective_date() -> None:
    metadata = extract_temporal_metadata("Effective Date: 12/09/2026")

    assert metadata.effective_date == date(2026, 9, 12)


def test_extracts_split_publication_date() -> None:
    metadata = extract_temporal_metadata("Publication Date\n2026-09-12")

    assert metadata.publication_date == date(2026, 9, 12)


def test_ignores_unlabelled_date() -> None:
    metadata = extract_temporal_metadata("Monetary Policy Committee\n12 September 2026\nPolicy Repo Rate")

    assert metadata.publication_date is None
    assert metadata.effective_date is None


def test_conflicting_dates_are_not_guessed() -> None:
    metadata = extract_temporal_metadata(
        "Published on 12 September 2026\nPublished on 13 September 2026"
    )

    assert metadata.publication_date is None
