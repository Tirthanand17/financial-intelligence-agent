from collections import Counter
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from hashlib import sha256
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from app.sources.registry import validate_source_url


@dataclass(frozen=True, slots=True)
class DiscoveredFeedItem:
    title: str | None
    url: str
    publication_date: date | None
    fingerprint: str


@dataclass(frozen=True, slots=True)
class FeedDiscoveryResult:
    items: tuple[DiscoveredFeedItem, ...]
    rejected_count: int = 0
    rejection_reasons: tuple[tuple[str, int], ...] = ()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, *names: str) -> str | None:
    wanted = {name.lower() for name in names}
    for child in element:
        if _local_name(child.tag) in wanted:
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return None


def _entry_link(entry: ET.Element) -> str | None:
    direct = _child_text(entry, "link")
    if direct:
        return direct.strip()
    for child in entry:
        if _local_name(child.tag) == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return None


def _publication_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _fingerprint(url: str, title: str | None, published: date | None) -> str:
    payload = "\x1f".join(
        (
            url.strip(),
            " ".join((title or "").split()),
            published.isoformat() if published else "",
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def discover_feed_items(
    content: bytes,
    *,
    source_id: str,
    limit: int,
) -> FeedDiscoveryResult:
    """Discover bounded, allow-listed item URLs from an RSS/Atom feed.

    This function never follows links. Every candidate item URL must independently
    pass the selected source's HTTPS host allow-list before it is returned.
    Duplicate links within the same feed are collapsed while preserving feed order.

    Rejections expose only symbolic aggregate reasons. They intentionally do not
    retain rejected URLs, raw XML, request headers, or exception text.
    """
    if limit < 1 or limit > 100:
        raise ValueError("discovery limit must be between 1 and 100")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("Invalid XML/RSS feed") from exc

    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]

    items: list[DiscoveredFeedItem] = []
    rejection_reasons: Counter[str] = Counter()
    seen_urls: set[str] = set()

    for entry in entries:
        if len(items) >= limit:
            break

        link = _entry_link(entry)
        if not link:
            rejection_reasons["missing_link"] += 1
            continue

        parsed = urlparse(link)
        if parsed.scheme != "https":
            rejection_reasons["non_https"] += 1
            continue

        try:
            validate_source_url(source_id, link)
        except ValueError:
            rejection_reasons["source_policy_rejection"] += 1
            continue

        normalized_url = link.strip()
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)

        title = _child_text(entry, "title")
        published = _publication_date(
            _child_text(entry, "pubDate", "published", "updated")
        )
        items.append(
            DiscoveredFeedItem(
                title=" ".join(title.split()) if title else None,
                url=normalized_url,
                publication_date=published,
                fingerprint=_fingerprint(normalized_url, title, published),
            )
        )

    return FeedDiscoveryResult(
        items=tuple(items),
        rejected_count=sum(rejection_reasons.values()),
        rejection_reasons=tuple(sorted(rejection_reasons.items())),
    )
