from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from urllib.parse import urlparse, urlunparse
import xml.etree.ElementTree as ET

from app.sources.registry import get_source, validate_source_url


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
        pass

    # Some first-party feeds publish an ISO-like timestamp without an RFC 2822
    # timezone, for example ``2026-09-11 18:36:55``. This remains a
    # source-provided publication date; retrieval time is never substituted.
    try:
        return datetime.fromisoformat(value.strip()).date()
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


def _normalize_feed_link(source_id: str, link: str) -> tuple[str | None, str | None]:
    """Return an HTTPS allow-listed item URL or a symbolic rejection reason.

    Some official legacy RSS feeds still publish ``http://`` item links even when
    the same first-party host serves the page over HTTPS. We never fetch the HTTP
    URL. Instead, only when the host is already explicitly allow-listed for this
    trusted source, preserve the exact host/path/query and upgrade the scheme to
    HTTPS before the normal source URL validator runs.

    Cross-host links, non-HTTP(S) schemes, malformed URLs, and any upgraded URL
    that still fails source policy remain rejected.
    """
    raw = link.strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()

    if parsed.scheme == "http":
        try:
            source = get_source(source_id)
        except ValueError:
            return None, "source_policy_rejection"

        if not host or host not in source.allowed_hosts:
            return None, "source_policy_rejection"

        parsed = parsed._replace(scheme="https")
        raw = urlunparse(parsed)
    elif parsed.scheme != "https":
        return None, "non_https"

    try:
        validate_source_url(source_id, raw)
    except ValueError:
        return None, "source_policy_rejection"

    return raw, None


def discover_feed_items(
    content: bytes,
    *,
    source_id: str,
    limit: int,
) -> FeedDiscoveryResult:
    """Discover bounded, allow-listed item URLs from an RSS/Atom feed.

    This function never follows links. Every candidate item URL must independently
    resolve to the selected source's HTTPS host allow-list before it is returned.
    A legacy HTTP link may only be upgraded in-memory to HTTPS when its hostname is
    already explicitly allow-listed for that same source; the HTTP URL is never
    requested. Duplicate links are collapsed while preserving feed order.

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

        normalized_url, rejection_reason = _normalize_feed_link(source_id, link)
        if normalized_url is None:
            rejection_reasons[rejection_reason or "source_policy_rejection"] += 1
            continue

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
