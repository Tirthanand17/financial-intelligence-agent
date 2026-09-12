from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.claims.eligibility import filter_eligible_claims
from app.claims.extractor import extract_structured_claims
from app.core.config import get_settings
from app.ingestion.chunker import chunk_text
from app.ingestion.downloader import DownloadedDocument, download_trusted_document
from app.ingestion.extractor import extract_document
from app.ingestion.quality import validate_extracted_document
from app.sources.metadata import extract_source_publication_date
from app.sources.registry import validate_source_url


DownloadDocument = Callable[[str, str], DownloadedDocument]


@dataclass(frozen=True, slots=True)
class DiscoveryPreflightResult:
    source_id: str
    requested_url: str
    final_url: str
    content_type: str
    sha256: str
    content_bytes: int
    title: str | None
    text_chars: int
    chunk_count: int
    publication_date: date | None
    eligible_claim_count: int


def preflight_discovered_url(
    source_id: str,
    url: str,
    *,
    download: DownloadDocument = download_trusted_document,
) -> DiscoveryPreflightResult:
    """Validate one discovered URL in memory without persisting any state.

    This is the Phase 7 observation boundary before queue processing is allowed to
    write evidence. The URL is re-validated immediately before download, then the
    normal trusted downloader, extractor, challenge-page quality gate, chunker,
    temporal metadata adapter, and structured-claim eligibility filter are run.

    No object-store write, vector upsert, document row, claim row, monitor audit
    row, discovery mutation, or trust transition occurs here.
    """
    source = validate_source_url(source_id, url)
    downloaded = download(source_id, url)
    extracted = extract_document(downloaded.content, downloaded.content_type)
    validate_extracted_document(extracted, downloaded.content_type)

    settings = get_settings()
    chunks = chunk_text(
        extracted.text,
        chunk_size=settings.chunk_size_chars,
        overlap=settings.chunk_overlap_chars,
    )
    if not chunks:
        raise ValueError("Preflight document produced no searchable chunks")

    publication_date = extract_source_publication_date(source_id, extracted.text)
    claims = extract_structured_claims(
        chunks=chunks,
        document_id="00000000-0000-0000-0000-000000000000",
        source_id=source_id,
        source_url=downloaded.final_url,
        entity=source.name,
        publication_date=publication_date,
    )
    eligible_claims = filter_eligible_claims(claims)

    return DiscoveryPreflightResult(
        source_id=source_id,
        requested_url=url,
        final_url=downloaded.final_url,
        content_type=downloaded.content_type,
        sha256=downloaded.sha256,
        content_bytes=len(downloaded.content),
        title=extracted.title,
        text_chars=len(extracted.text),
        chunk_count=len(chunks),
        publication_date=publication_date,
        eligible_claim_count=len(eligible_claims),
    )
