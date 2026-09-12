from dataclasses import dataclass


_XML_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}


@dataclass(frozen=True, slots=True)
class FeedProbeDecision:
    passed: bool
    reason: str
    blockers: tuple[str, ...] = ()


def assess_feed_probe(
    *,
    content_type: str,
    discovered_count: int,
    rejected_count: int,
    limit: int,
) -> FeedProbeDecision:
    """Validate one read-only live feed probe before monitor registration.

    This checkpoint is intentionally strict: the source must return XML, yield at
    least one allow-listed item within the explicit bound, and produce no rejected
    items in the inspected prefix. A rejection means the feed shape or source
    policy needs human review before the source can be added to the monitor
    registry.
    """
    blockers: list[str] = []

    if content_type not in _XML_CONTENT_TYPES:
        blockers.append("feed:unexpected_content_type")
    if limit < 1 or limit > 100:
        blockers.append("feed:invalid_limit")
    if discovered_count < 1:
        blockers.append("feed:no_items_discovered")
    if discovered_count > limit:
        blockers.append("feed:discovery_exceeded_limit")
    if rejected_count != 0:
        blockers.append("feed:rejected_items_present")

    unique = tuple(dict.fromkeys(blockers))
    if unique:
        return FeedProbeDecision(
            passed=False,
            reason="feed_probe_not_ready",
            blockers=unique,
        )

    return FeedProbeDecision(passed=True, reason="feed_probe_ready")
