from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.claims.eligibility import filter_eligible_claims
from app.claims.extractor import extract_structured_claims
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
    downloaded: DownloadedDocument = field(repr=False, compare=False)


def preflight_discovered_url(
    source_id: str,
    url: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    download: DownloadDocument = download_trusted_document,
) -> DiscoveryPreflightResult:
    """Validate one discovered URL in memory without persisting any state.

    The caller supplies the already-resolved production chunk settings so this
    pure preflight helper does not need database/object/vector credentials just to
    validate extraction. The URL is re-validated immediately before download,
    then the normal trusted downloader, extractor, challenge-page quality gate,
    chunker, temporal metadata adapter, and structured-claim eligibility filter
    are run.

    The accepted ``DownloadedDocument`` is retained privately on the result so a
    controlled caller can persist the exact already-validated bytes without a
    second public download. The raw bytes are excluded from the dataclass repr.

    No object-store write, vector upsert, document row, claim row, monitor audit
    row, discovery mutation, or trust transition occurs here.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")

    source = validate_source_url(source_id, url)
    downloaded = download(source_id, url)
    extracted = extract_document(downloaded.content, downloaded.content_type)
    validate_extracted_document(extracted, downloaded.content_type)

    chunks = chunk_text(
        extracted.text,
        chunk_size=chunk_size,
        overlap=chunk_overlap,
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
        downloaded=downloaded,
    )
