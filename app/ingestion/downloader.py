import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.sources.registry import SourceDefinition, validate_source_url


_TRANSIENT_DOWNLOAD_ERRORS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)
_MAX_DOWNLOAD_ATTEMPTS = 3
_RETRY_DELAYS_SECONDS = (1.0, 2.0)
_XML_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}


@dataclass(frozen=True, slots=True)
class DownloadedDocument:
    source: SourceDefinition
    source_url: str
    final_url: str
    content: bytes
    content_type: str
    sha256: str
    retrieved_at: datetime


def _validate_redirect_target(source_url: str, final_url: str, source: SourceDefinition) -> None:
    final = urlparse(final_url)
    final_host = (final.hostname or "").lower()
    if final_host not in source.allowed_hosts:
        raise ValueError("Trusted source redirected to a non-allow-listed host")

    requested = urlparse(source_url)
    requested_path = requested.path.rstrip("/")
    final_path = final.path.rstrip("/")

    # A document/detail URL that silently collapses to the source homepage is
    # not the requested evidence. Reject it instead of indexing unrelated home
    # page content under the original document URL.
    if requested_path and not final_path:
        raise ValueError(
            "Trusted source redirected the requested document to its homepage; "
            "the response was rejected because it is not the requested evidence."
        )


def _download_trusted_document_once(source_id: str, url: str) -> DownloadedDocument:
    """Perform one complete trusted-source download attempt.

    Nothing is persisted by this helper. If a connection resets or a streamed
    response fails part-way through, the partial in-memory buffer is discarded
    and the outer retry wrapper may safely start a fresh request.
    """
    settings = get_settings()
    source = validate_source_url(source_id, url)
    max_bytes = settings.max_download_mb * 1024 * 1024

    headers = {
        "User-Agent": "FinancialIntelligenceAgent/0.1 (+research; source-grounded ingestion)",
        "Accept": (
            "text/html,application/pdf,application/rss+xml,application/atom+xml,"
            "application/xml,text/xml,text/plain;q=0.9,*/*;q=0.5"
        ),
    }

    with httpx.Client(follow_redirects=True, timeout=45.0, headers=headers) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()

            final_url = str(response.url)
            _validate_redirect_target(url, final_url, source)

            declared_length = response.headers.get("content-length")
            if declared_length and declared_length.isdigit() and int(declared_length) > max_bytes:
                raise ValueError(f"Document exceeds configured {settings.max_download_mb} MB limit")

            buffer = bytearray()
            for block in response.iter_bytes(chunk_size=64 * 1024):
                buffer.extend(block)
                if len(buffer) > max_bytes:
                    raise ValueError(f"Document exceeds configured {settings.max_download_mb} MB limit")

            content = bytes(buffer)
            content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()

    if content_type == "application/octet-stream":
        lower_url = final_url.lower()
        if lower_url.endswith(".pdf"):
            content_type = "application/pdf"
        elif lower_url.endswith((".html", ".htm")):
            content_type = "text/html"
        elif lower_url.endswith((".xml", ".rss")):
            content_type = "application/xml"

    allowed_types = {"application/pdf", "text/html", "text/plain", *_XML_CONTENT_TYPES}
    if content_type not in allowed_types:
        raise ValueError(f"Unsupported content type: {content_type}")

    return DownloadedDocument(
        source=source,
        source_url=url,
        final_url=final_url,
        content=content,
        content_type=content_type,
        sha256=sha256(content).hexdigest(),
        retrieved_at=datetime.now(UTC),
    )


def download_trusted_document(source_id: str, url: str) -> DownloadedDocument:
    """Download allow-listed evidence with bounded transient-network retries.

    Retries are deliberately limited to transport failures such as connection
    resets/timeouts. HTTP errors, redirect-policy violations, unsupported content
    types, and size limits are not retried because repeating those requests would
    not make unsafe or invalid evidence acceptable.
    """
    last_error: Exception | None = None

    for attempt in range(1, _MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            return _download_trusted_document_once(source_id, url)
        except _TRANSIENT_DOWNLOAD_ERRORS as exc:
            last_error = exc
            if attempt >= _MAX_DOWNLOAD_ATTEMPTS:
                break
            time.sleep(_RETRY_DELAYS_SECONDS[attempt - 1])

    raise ConnectionError(
        f"Trusted source download failed after {_MAX_DOWNLOAD_ATTEMPTS} transient "
        f"network attempts for source {source_id!r}."
    ) from last_error
