from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import httpx

from app.ingestion.downloader import download_trusted_document
from app.monitoring.discovery import discover_feed_items
from app.monitoring.models import MonitorDefinition
from app.sources.registry import validate_source_url


_XML_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}


class FeedDownload(Protocol):
    content: bytes
    content_type: str
    sha256: str


DownloadFeed = Callable[[str, str], FeedDownload]


@dataclass(frozen=True, slots=True)
class ManualFeedProbeResult:
    status: str
    reason: str
    discovered_count: int = 0
    rejected_count: int = 0
    rejection_reasons: tuple[tuple[str, int], ...] = ()
    content_sha256: str | None = None
    latest_publication_date: date | None = None


def probe_feed_read_only(
    monitor: MonitorDefinition,
    *,
    download_feed: DownloadFeed = download_trusted_document,
) -> ManualFeedProbeResult:
    """Fetch and inspect one configured feed without any persistence writes.

    This is a manual validation primitive, not a scheduler. It validates the
    configured monitor URL, downloads only that URL through the existing trusted
    downloader, parses a bounded set of allow-listed feed entries, and returns
    aggregate non-secret diagnostics. It does not write monitor state, queue
    discoveries, ingest item URLs, or change claim/trust state.
    """
    try:
        validate_source_url(monitor.source_id, monitor.url)
        downloaded = download_feed(monitor.source_id, monitor.url)
    except ConnectionError:
        return ManualFeedProbeResult(
            status="failed",
            reason="transient_network_error",
        )
    except httpx.HTTPError:
        return ManualFeedProbeResult(
            status="failed",
            reason="http_error",
        )
    except ValueError:
        return ManualFeedProbeResult(
            status="rejected",
            reason="source_policy_rejection",
        )

    content_type = downloaded.content_type.split(";", 1)[0].lower()
    if content_type not in _XML_CONTENT_TYPES:
        return ManualFeedProbeResult(
            status="rejected",
            reason="unexpected_feed_content_type",
            content_sha256=downloaded.sha256,
        )

    try:
        discovery = discover_feed_items(
            downloaded.content,
            source_id=monitor.source_id,
            limit=monitor.max_new_documents_per_run,
        )
    except ValueError:
        return ManualFeedProbeResult(
            status="rejected",
            reason="invalid_feed",
            content_sha256=downloaded.sha256,
        )

    dated = [
        item.publication_date
        for item in discovery.items
        if item.publication_date is not None
    ]
    latest_date = max(dated) if dated else None

    return ManualFeedProbeResult(
        status="ok",
        reason="feed_probe_completed",
        discovered_count=len(discovery.items),
        rejected_count=discovery.rejected_count,
        rejection_reasons=discovery.rejection_reasons,
        content_sha256=downloaded.sha256,
        latest_publication_date=latest_date,
    )
