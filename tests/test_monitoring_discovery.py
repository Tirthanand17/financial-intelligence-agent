from datetime import date

import pytest

from app.monitoring.discovery import discover_feed_items


def test_discovers_allowlisted_rbi_items_without_following_links() -> None:
    content = b"""<?xml version='1.0'?>
    <rss version='2.0'><channel>
      <item>
        <title>Monetary Policy Statement</title>
        <link>https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=123</link>
        <pubDate>Fri, 05 Jun 2026 10:00:00 +0530</pubDate>
      </item>
      <item>
        <title>Governor Statement</title>
        <link>https://rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=124</link>
        <pubDate>Fri, 05 Jun 2026 11:00:00 +0530</pubDate>
      </item>
    </channel></rss>"""

    result = discover_feed_items(content, source_id="rbi", limit=10)

    assert result.rejected_count == 0
    assert result.rejection_reasons == ()
    assert len(result.items) == 2
    assert result.items[0].title == "Monetary Policy Statement"
    assert result.items[0].publication_date == date(2026, 6, 5)
    assert len(result.items[0].fingerprint) == 64


def test_rejects_cross_host_and_non_https_items() -> None:
    content = b"""<rss><channel>
      <item><title>Bad host</title><link>https://example.com/item</link></item>
      <item><title>HTTP</title><link>http://www.rbi.org.in/item</link></item>
      <item><title>Good</title><link>https://www.rbi.org.in/item</link></item>
    </channel></rss>"""

    result = discover_feed_items(content, source_id="rbi", limit=10)

    assert result.rejected_count == 2
    assert result.rejection_reasons == (
        ("non_https", 1),
        ("source_policy_rejection", 1),
    )
    assert [item.url for item in result.items] == ["https://www.rbi.org.in/item"]


def test_missing_link_is_reported_symbolically() -> None:
    content = b"""<rss><channel>
      <item><title>No link</title></item>
    </channel></rss>"""

    result = discover_feed_items(content, source_id="rbi", limit=10)

    assert result.items == ()
    assert result.rejected_count == 1
    assert result.rejection_reasons == (("missing_link", 1),)


def test_duplicate_feed_links_are_collapsed() -> None:
    content = b"""<rss><channel>
      <item><title>One</title><link>https://www.rbi.org.in/item</link></item>
      <item><title>Duplicate</title><link>https://www.rbi.org.in/item</link></item>
    </channel></rss>"""

    result = discover_feed_items(content, source_id="rbi", limit=10)

    assert len(result.items) == 1


def test_discovery_is_bounded_by_monitor_limit() -> None:
    content = b"""<rss><channel>
      <item><title>1</title><link>https://www.rbi.org.in/1</link></item>
      <item><title>2</title><link>https://www.rbi.org.in/2</link></item>
      <item><title>3</title><link>https://www.rbi.org.in/3</link></item>
    </channel></rss>"""

    result = discover_feed_items(content, source_id="rbi", limit=2)

    assert [item.url for item in result.items] == [
        "https://www.rbi.org.in/1",
        "https://www.rbi.org.in/2",
    ]


def test_atom_href_links_are_supported() -> None:
    content = b"""<feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <title>RBI update</title>
        <link href='https://www.rbi.org.in/atom-item'/>
        <updated>Fri, 05 Jun 2026 10:00:00 +0530</updated>
      </entry>
    </feed>"""

    result = discover_feed_items(content, source_id="rbi", limit=10)

    assert len(result.items) == 1
    assert result.items[0].url == "https://www.rbi.org.in/atom-item"


def test_invalid_xml_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid XML/RSS feed"):
        discover_feed_items(b"<rss>", source_id="rbi", limit=10)


def test_limit_is_hard_bounded() -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        discover_feed_items(b"<rss/>", source_id="rbi", limit=101)
