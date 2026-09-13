import json

import pytest

from app.monitoring.registry import MONITORS, get_monitor, validate_monitor_registry
from app.monitoring.source_coverage import build_source_coverage, primary_india_monitoring_gaps
from app.sources.mospi import (
    MOSPI_LATEST_RELEASES_API_URL,
    discover_mospi_latest_releases,
)
from app.sources.registry import TRUSTED_SOURCES, validate_source_url


def _payload(*rows: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "code": 200,
            "status": 200,
            "message": "Latest Releases retrieved successfully.",
            "data": list(rows),
        }
    ).encode("utf-8")


def test_mospi_monitor_is_registered_with_official_api_endpoint() -> None:
    validate_monitor_registry()
    monitor = get_monitor("mospi-latest-releases-api")

    assert monitor.source_id == "mospi"
    assert monitor.url == MOSPI_LATEST_RELEASES_API_URL
    assert monitor.interval_minutes == 60
    assert monitor.max_new_documents_per_run == 10
    assert monitor.enabled is True
    assert validate_source_url("mospi", monitor.url).source_id == "mospi"


def test_mospi_api_parser_discovers_bounded_first_party_pdfs() -> None:
    content = _payload(
        {
            "id": "1",
            "title": "Latest CPI release",
            "published_year": "2026-09-10",
            "file_one": {
                "path": "uploads/latestReleases/cpi.pdf",
                "filemime": "application/pdf",
                "filename": "cpi.pdf",
                "filesize": 1234,
            },
        },
        {
            "id": "2",
            "title": "Latest GDP release",
            "published_year": "2026-09-02",
            "file_one": {
                "path": "uploads/latestReleases/gdp.pdf",
                "filemime": "application/pdf",
                "filename": "gdp.pdf",
                "filesize": 2345,
            },
        },
    )

    result = discover_mospi_latest_releases(content, limit=1)

    assert result.rejected_count == 0
    assert len(result.items) == 1
    assert result.items[0].title == "Latest CPI release"
    assert result.items[0].publication_date.isoformat() == "2026-09-10"
    assert result.items[0].url == "https://www.mospi.gov.in/uploads/latestReleases/cpi.pdf"


def test_mospi_api_parser_rejects_cross_host_and_non_pdf_records() -> None:
    content = _payload(
        {
            "title": "Cross host",
            "published_year": "2026-09-10",
            "file_one": {
                "path": "https://example.com/uploads/latestReleases/unsafe.pdf",
                "filemime": "application/pdf",
            },
        },
        {
            "title": "Not PDF",
            "published_year": "2026-09-10",
            "file_one": {
                "path": "uploads/latestReleases/archive.zip",
                "filemime": "application/zip",
            },
        },
        {
            "title": "Safe PDF",
            "published_year": "2026-09-10",
            "file_one": {
                "path": "uploads/latestReleases/safe.pdf",
                "filemime": "application/pdf",
            },
        },
    )

    result = discover_mospi_latest_releases(content, limit=10)

    assert [item.title for item in result.items] == ["Safe PDF"]
    assert result.rejected_count == 2
    assert result.rejection_reasons == (
        ("source_policy_rejection", 1),
        ("unsupported_file_type", 1),
    )


def test_mospi_api_parser_fails_closed_on_invalid_schema() -> None:
    with pytest.raises(ValueError, match="Invalid MoSPI API JSON"):
        discover_mospi_latest_releases(b"{", limit=10)

    with pytest.raises(ValueError, match="Unexpected MoSPI API response"):
        discover_mospi_latest_releases(b'{"code":500,"data":[]}', limit=10)


def test_phase15_primary_india_monitoring_gap_is_closed() -> None:
    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    by_id = {row.source_id: row for row in coverage}

    assert by_id["sebi"].monitor_ids == ("sebi-rss",)
    assert by_id["nse"].monitor_ids == ("nse-daily-buyback-rss",)
    assert by_id["mospi"].monitor_ids == ("mospi-latest-releases-api",)
    assert primary_india_monitoring_gaps(coverage) == ()
