from datetime import date

import pytest

from app.monitoring.discovery import discover_feed_items
from app.sources.registry import validate_source_url

NSE_FEED = "https://nsearchives.nseindia.com/content/RSS/Daily_Buyback.xml"


def test_nse_archive_host_is_explicitly_allowlisted() -> None:
    assert validate_source_url("nse", NSE_FEED).source_id == "nse"


def test_nse_similar_or_cross_host_is_rejected() -> None:
    with pytest.raises(ValueError, match="not allow-listed"):
        validate_source_url("nse", "https://nsearchives.nseindia.com.evil.example/content/RSS/Daily_Buyback.xml")


def test_nse_iso_like_source_date_is_preserved_without_retrieval_fallback() -> None:
    content = b"""<rss><channel><item>
      <title>SIS LIMITED</title>
      <link>https://nsearchives.nseindia.com/corporate/SIS.pdf</link>
      <pubDate>2026-09-11 18:36:55</pubDate>
    </item></channel></rss>"""
    result = discover_feed_items(content, source_id="nse", limit=10)
    assert result.rejected_count == 0
    assert result.items[0].publication_date == date(2026, 9, 11)


def test_nse_feed_discovery_stays_bounded_and_first_party() -> None:
    content = b"""<rss><channel>
      <item><title>One</title><link>https://nsearchives.nseindia.com/corporate/one.pdf</link></item>
      <item><title>Two</title><link>https://archives.nseindia.com/corporate/two.pdf</link></item>
      <item><title>Three</title><link>https://nsearchives.nseindia.com/corporate/three.pdf</link></item>
    </channel></rss>"""
    result = discover_feed_items(content, source_id="nse", limit=2)
    assert result.rejected_count == 0
    assert len(result.items) == 2
    assert [item.title for item in result.items] == ["One", "Two"]


def test_nse_monitor_registration_is_bounded_and_official() -> None:
    from app.monitoring.registry import get_monitor, validate_monitor_registry

    validate_monitor_registry()
    monitor = get_monitor("nse-daily-buyback-rss")
    assert monitor.source_id == "nse"
    assert monitor.url == NSE_FEED
    assert monitor.interval_minutes == 60
    assert monitor.max_new_documents_per_run == 10
    assert monitor.enabled is True
