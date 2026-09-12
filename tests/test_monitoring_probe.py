from types import SimpleNamespace

import httpx

from app.monitoring.models import MonitorDefinition
from app.monitoring.probe import probe_feed_read_only


def _monitor() -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=2,
    )


def test_probe_returns_bounded_aggregate_feed_diagnostics_only() -> None:
    feed = b"""<rss><channel>
      <item>
        <title>One</title>
        <link>https://www.rbi.org.in/1</link>
        <pubDate>Fri, 11 Sep 2026 10:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Two</title>
        <link>https://www.rbi.org.in/2</link>
        <pubDate>Sat, 12 Sep 2026 10:00:00 GMT</pubDate>
      </item>
      <item><title>Three</title><link>https://www.rbi.org.in/3</link></item>
    </channel></rss>"""

    result = probe_feed_read_only(
        _monitor(),
        download_feed=lambda *_: SimpleNamespace(
            content=feed,
            content_type="application/rss+xml",
            sha256="a" * 64,
        ),
    )

    assert result.status == "ok"
    assert result.reason == "feed_probe_completed"
    assert result.discovered_count == 2
    assert result.rejected_count == 0
    assert result.rejection_reasons == ()
    assert result.content_sha256 == "a" * 64
    assert result.latest_publication_date is not None
    assert result.latest_publication_date.isoformat() == "2026-09-12"


def test_cross_host_feed_item_is_counted_rejected_without_following() -> None:
    feed = b"""<rss><channel>
      <item><title>Unsafe</title><link>https://example.com/1</link></item>
      <item><title>Safe</title><link>https://www.rbi.org.in/2</link></item>
    </channel></rss>"""

    result = probe_feed_read_only(
        _monitor(),
        download_feed=lambda *_: SimpleNamespace(
            content=feed,
            content_type="application/xml",
            sha256="b" * 64,
        ),
    )

    assert result.status == "ok"
    assert result.discovered_count == 1
    assert result.rejected_count == 1
    assert result.rejection_reasons == (("source_policy_rejection", 1),)


def test_non_xml_response_is_rejected() -> None:
    result = probe_feed_read_only(
        _monitor(),
        download_feed=lambda *_: SimpleNamespace(
            content=b"<html>not feed</html>",
            content_type="text/html",
            sha256="c" * 64,
        ),
    )

    assert result.status == "rejected"
    assert result.reason == "unexpected_feed_content_type"


def test_network_failure_returns_symbolic_error_only() -> None:
    def broken(*_):
        raise ConnectionError("raw network details")

    result = probe_feed_read_only(_monitor(), download_feed=broken)

    assert result.status == "failed"
    assert result.reason == "transient_network_error"
    assert result.content_sha256 is None


def test_http_error_returns_symbolic_error_only() -> None:
    request = httpx.Request("GET", "https://rbi.org.in/pressreleases_rss.xml")
    response = httpx.Response(503, request=request)

    def broken(*_):
        raise httpx.HTTPStatusError("raw HTTP details", request=request, response=response)

    result = probe_feed_read_only(_monitor(), download_feed=broken)

    assert result.status == "failed"
    assert result.reason == "http_error"


def test_invalid_configured_monitor_url_is_rejected_before_download() -> None:
    monitor = MonitorDefinition(
        monitor_id="tampered",
        source_id="rbi",
        url="https://example.com/feed.xml",
        interval_minutes=60,
        enabled=True,
    )
    calls = 0

    def download(*_):
        nonlocal calls
        calls += 1
        raise AssertionError("download must not run")

    result = probe_feed_read_only(monitor, download_feed=download)

    assert calls == 0
    assert result.status == "rejected"
    assert result.reason == "source_policy_rejection"
