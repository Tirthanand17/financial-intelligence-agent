import pytest

from app.monitoring.discovery import discover_feed_items
from app.monitoring.registry import MONITORS, get_monitor, validate_monitor_registry
from app.monitoring.source_coverage import build_source_coverage, primary_india_monitoring_gaps
from app.sources.registry import TRUSTED_SOURCES, validate_source_url


def test_sebi_monitor_is_registered_with_verified_official_endpoint() -> None:
    validate_monitor_registry()
    monitor = get_monitor("sebi-rss")

    assert monitor.source_id == "sebi"
    assert monitor.url == "https://www.sebi.gov.in/sebirss.xml"
    assert monitor.interval_minutes == 60
    assert monitor.max_new_documents_per_run == 10
    assert monitor.enabled is True
    assert validate_source_url("sebi", monitor.url).source_id == "sebi"


def test_sebi_source_policy_rejects_non_https_and_cross_host_urls() -> None:
    with pytest.raises(ValueError, match="Only HTTPS"):
        validate_source_url("sebi", "http://www.sebi.gov.in/sebirss.xml")

    with pytest.raises(ValueError, match="not allow-listed"):
        validate_source_url("sebi", "https://example.com/sebirss.xml")


def test_sebi_feed_parser_allows_missing_publication_dates_and_stays_bounded() -> None:
    content = b"""<rss><channel>
      <item><title>One</title><link>https://www.sebi.gov.in/legal/orders/one.html</link></item>
      <item><title>Two</title><link>https://www.sebi.gov.in/legal/orders/two.html</link></item>
      <item><title>Three</title><link>https://www.sebi.gov.in/legal/orders/three.html</link></item>
    </channel></rss>"""

    result = discover_feed_items(content, source_id="sebi", limit=2)

    assert result.rejected_count == 0
    assert len(result.items) == 2
    assert [item.title for item in result.items] == ["One", "Two"]
    assert all(item.publication_date is None for item in result.items)


def test_sebi_feed_parser_rejects_cross_host_and_non_http_schemes() -> None:
    content = b"""<rss><channel>
      <item><title>Cross host</title><link>https://example.com/item</link></item>
      <item><title>FTP</title><link>ftp://www.sebi.gov.in/item</link></item>
      <item><title>Good</title><link>https://www.sebi.gov.in/item</link></item>
    </channel></rss>"""

    result = discover_feed_items(content, source_id="sebi", limit=10)

    assert [item.url for item in result.items] == ["https://www.sebi.gov.in/item"]
    assert result.rejected_count == 2
    assert result.rejection_reasons == (
        ("non_https", 1),
        ("source_policy_rejection", 1),
    )


def test_sebi_feed_parser_fails_closed_on_malformed_xml() -> None:
    with pytest.raises(ValueError, match="Invalid XML/RSS feed"):
        discover_feed_items(b"<rss>", source_id="sebi", limit=10)


def test_sebi_nse_and_mospi_registration_closes_primary_india_gap() -> None:
    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    by_id = {row.source_id: row for row in coverage}

    assert by_id["sebi"].monitor_ids == ("sebi-rss",)
    assert by_id["nse"].monitor_ids == ("nse-daily-buyback-rss",)
    assert by_id["mospi"].monitor_ids == ("mospi-latest-releases-api",)
    assert primary_india_monitoring_gaps(coverage) == ()
