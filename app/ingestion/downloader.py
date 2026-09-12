from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.sources.registry import SourceDefinition, validate_source_url


@dataclass(frozen=True, slots=True)
class DownloadedDocument:
    source: SourceDefinition
    source_url: str
    final_url: str
    content: bytes
    content_type: str
    sha256: str
    retrieved_at: datetime


def download_trusted_document(source_id: str, url: str) -> DownloadedDocument:
    settings = get_settings()
    source = validate_source_url(source_id, url)
    max_bytes = settings.max_download_mb * 1024 * 1024

    headers = {
        "User-Agent": "FinancialIntelligenceAgent/0.1 (+research; source-grounded ingestion)",
        "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.5",
    }

    with httpx.Client(follow_redirects=True, timeout=45.0, headers=headers) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()

            final_url = str(response.url)
            final_host = (urlparse(final_url).hostname or "").lower()
            if final_host not in source.allowed_hosts:
                raise ValueError("Trusted source redirected to a non-allow-listed host")

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

    allowed_types = {"application/pdf", "text/html", "text/plain"}
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
