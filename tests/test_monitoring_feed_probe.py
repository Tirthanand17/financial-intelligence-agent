from app.monitoring.feed_probe import assess_feed_probe


def test_feed_probe_accepts_bounded_clean_xml_discovery() -> None:
    decision = assess_feed_probe(
        content_type="application/xml",
        discovered_count=10,
        rejected_count=0,
        limit=10,
    )

    assert decision.passed is True
    assert decision.blockers == ()


def test_feed_probe_rejects_non_xml_or_empty_feed() -> None:
    decision = assess_feed_probe(
        content_type="text/html",
        discovered_count=0,
        rejected_count=0,
        limit=10,
    )

    assert decision.passed is False
    assert "feed:unexpected_content_type" in decision.blockers
    assert "feed:no_items_discovered" in decision.blockers


def test_feed_probe_requires_review_when_item_policy_rejects() -> None:
    decision = assess_feed_probe(
        content_type="application/rss+xml",
        discovered_count=9,
        rejected_count=1,
        limit=10,
    )

    assert decision.passed is False
    assert decision.blockers == ("feed:rejected_items_present",)


def test_feed_probe_enforces_bound() -> None:
    decision = assess_feed_probe(
        content_type="application/xml",
        discovered_count=11,
        rejected_count=0,
        limit=10,
    )

    assert decision.passed is False
    assert "feed:discovery_exceeded_limit" in decision.blockers
