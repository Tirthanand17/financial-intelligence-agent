import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from urllib.parse import unquote, urljoin, urlparse

import httpx

from app.core.config import get_settings
from app.monitoring.discovery import DiscoveredFeedItem, FeedDiscoveryResult
from app.sources.registry import validate_source_url


MOSPI_LATEST_RELEASES_API_URL = (
    "https://www.mospi.gov.in/api/latest-release/get-web-latest-release-list"
)
_MOSPI_RELEASE_BASE_URL = "https://www.mospi.gov.in/"
_MOSPI_RELEASE_PATH_PREFIX = "/uploads/latestReleases/"
_MAX_API_ITEMS = 10
_TRANSIENT_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


@dataclass(frozen=True, slots=True)
class MospiApiPayload:
    content: bytes
    content_type: str


def _request_payload() -> dict[str, object]:
    return {
        "page_no": 1,
        "page_size": _MAX_API_ITEMS,
        "search_term": "",
        "sort_field": "published_year",
        "sort_order": "DESC",
        "start_date": "",
        "end_date": "",
        "data_source": "web",
        "lang": "en",
    }


def _validate_api_final_url(requested_url: str, final_url: str) -> None:
    validate_source_url("mospi", final_url)
    requested = urlparse(requested_url)
    final = urlparse(final_url)
    if final.path.rstrip("/") != requested.path.rstrip("/"):
        raise ValueError("MoSPI API redirected away from the approved endpoint")


def download_mospi_latest_releases(
    source_id: str,
    url: str,
) -> MospiApiPayload:
    if source_id != "mospi":
        raise ValueError("MoSPI API downloader only accepts the mospi source")
    if url != MOSPI_LATEST_RELEASES_API_URL:
        raise ValueError("Unapproved MoSPI monitoring endpoint")

    validate_source_url(source_id, url)
    settings = get_settings()
    max_bytes = settings.max_download_mb * 1024 * 1024
    headers = {
        "User-Agent": "FinancialIntelligenceAgent/0.1 (+research; source-grounded monitoring)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with httpx.Client(follow_redirects=True, timeout=45.0, headers=headers) as client:
                response = client.post(url, json=_request_payload())
                response.raise_for_status()
            break
        except _TRANSIENT_ERRORS as exc:
            last_error = exc
            if attempt >= 3:
                raise ConnectionError("MoSPI API download failed after bounded retries") from exc
            time.sleep(float(attempt))
    else:
        raise ConnectionError("MoSPI API download failed") from last_error

    final_url = str(response.url)
    _validate_api_final_url(url, final_url)
    content = response.content
    if len(content) > max_bytes:
        raise ValueError(f"Document exceeds configured {settings.max_download_mb} MB limit")

    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/json":
        raise ValueError("MoSPI monitoring endpoint did not return JSON")

    return MospiApiPayload(content=content, content_type=content_type)


def _parse_publication_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("invalid_publication_date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("invalid_publication_date") from exc


def _fingerprint(url: str, title: str | None, published: date | None) -> str:
    payload = "\x1f".join(
        (url, " ".join((title or "").split()), published.isoformat() if published else "")
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def discover_mospi_latest_releases(
    content: bytes,
    *,
    limit: int,
) -> FeedDiscoveryResult:
    if limit < 1 or limit > _MAX_API_ITEMS:
        raise ValueError("MoSPI discovery limit must be between 1 and 10")

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid MoSPI API JSON") from exc

    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise ValueError("Unexpected MoSPI API response")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("Unexpected MoSPI API data shape")

    items: list[DiscoveredFeedItem] = []
    rejections: Counter[str] = Counter()
    seen_urls: set[str] = set()

    for row in rows:
        if len(items) >= limit:
            break
        if not isinstance(row, dict):
            rejections["invalid_record"] += 1
            continue

        file_one = row.get("file_one")
        if not isinstance(file_one, dict):
            rejections["missing_pdf"] += 1
            continue

        path = file_one.get("path")
        filemime = file_one.get("filemime")
        if not isinstance(path, str) or not path.strip():
            rejections["missing_pdf"] += 1
            continue
        if filemime != "application/pdf" or not path.lower().endswith(".pdf"):
            rejections["unsupported_file_type"] += 1
            continue

        candidate = urljoin(_MOSPI_RELEASE_BASE_URL, path.strip())
        parsed = urlparse(candidate)
        decoded_path = unquote(parsed.path)
        if (
            not decoded_path.startswith(_MOSPI_RELEASE_PATH_PREFIX)
            or ".." in decoded_path.split("/")
            or parsed.query
            or parsed.fragment
        ):
            rejections["source_policy_rejection"] += 1
            continue
        try:
            validate_source_url("mospi", candidate)
        except ValueError:
            rejections["source_policy_rejection"] += 1
            continue

        try:
            published = _parse_publication_date(row.get("published_year"))
        except ValueError:
            rejections["invalid_publication_date"] += 1
            continue

        title_value = row.get("title")
        title = " ".join(title_value.split()) if isinstance(title_value, str) else None
        if candidate in seen_urls:
            continue
        seen_urls.add(candidate)
        items.append(
            DiscoveredFeedItem(
                title=title,
                url=candidate,
                publication_date=published,
                fingerprint=_fingerprint(candidate, title, published),
            )
        )

    return FeedDiscoveryResult(
        items=tuple(items),
        rejected_count=sum(rejections.values()),
        rejection_reasons=tuple(sorted(rejections.items())),
    )
