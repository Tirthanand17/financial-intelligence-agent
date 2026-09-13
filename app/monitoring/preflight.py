from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.claims.eligibility import filter_eligible_claims
from app.claims.extractor import extract_structured_claims
from app.ingestion.chunker import chunk_text
from app.ingestion.downloader import DownloadedDocument, download_trusted_document
from app.ingestion.extractor import ExtractedDocument, extract_document
from app.ingestion.quality import validate_extracted_document
from app.sources.metadata import extract_source_publication_date
from app.sources.registry import validate_source_url
from app.sources.sebi import extract_sebi_primary_pdf_url


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


def _validated_extraction(downloaded: DownloadedDocument) -> ExtractedDocument:
    extracted = extract_document(downloaded.content, downloaded.content_type)
    validate_extracted_document(extracted, downloaded.content_type)
    return extracted


def _resolve_preflight_evidence(
    source_id: str,
    requested_url: str,
    *,
    download: DownloadDocument,
) -> tuple[DownloadedDocument, ExtractedDocument, date | None]:
    """Resolve the exact evidence bytes approved for a one-item preflight.

    Normally the discovered URL itself is the evidence document. SEBI order and
    enforcement entries are a documented exception: the discovered URL can be a
    small first-party detail wrapper whose primary evidence is one first-party
    PDF attachment. For that source only, a single narrowly allow-listed PDF may
    be resolved and downloaded once. Arbitrary or ambiguous links are never
    followed.
    """
    initial = download(source_id, requested_url)
    initial_extracted = _validated_extraction(initial)
    page_publication_date = extract_source_publication_date(
        source_id,
        initial_extracted.text,
    )

    if source_id != "sebi" or initial.content_type != "text/html":
        publication_date = (
            extract_source_publication_date(source_id, initial_extracted.text)
            or initial.publication_date_hint
        )
        return initial, initial_extracted, publication_date

    attachment_url = extract_sebi_primary_pdf_url(initial.content, initial.final_url)
    if attachment_url is None:
        # A substantive SEBI HTML article can still be valid evidence. Short
        # wrapper pages, however, are not allowed into trusted storage without
        # their explicit first-party PDF payload.
        if len(initial_extracted.text) < 500:
            raise ValueError(
                "SEBI detail page is a thin HTML wrapper without one validated "
                "first-party PDF attachment"
            )
        return initial, initial_extracted, page_publication_date

    attachment = download(source_id, attachment_url)
    if attachment.content_type != "application/pdf":
        raise ValueError("SEBI approved attachment did not return PDF evidence")

    attachment_extracted = _validated_extraction(attachment)
    publication_date = (
        extract_source_publication_date(source_id, attachment_extracted.text)
        or page_publication_date
    )

    # Preserve the discovered wrapper as source provenance while the final URL,
    # hash and bytes identify the exact PDF evidence that passed preflight.
    evidence = DownloadedDocument(
        source=attachment.source,
        source_url=requested_url,
        final_url=attachment.final_url,
        content=attachment.content,
        content_type=attachment.content_type,
        sha256=attachment.sha256,
        retrieved_at=attachment.retrieved_at,
        publication_date_hint=publication_date,
    )
    return evidence, attachment_extracted, publication_date


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

    For an allow-listed SEBI detail wrapper, preflight may resolve exactly one
    first-party ``/sebi_data/attachdocs/...pdf`` attachment. The PDF is downloaded
    once, retained privately on the result, and becomes the exact evidence bytes
    eligible for controlled persistence. No arbitrary links are followed.

    The accepted ``DownloadedDocument`` is retained privately on the result so a
    controlled caller can persist the exact already-validated bytes without a
    second public evidence download. The raw bytes are excluded from the dataclass
    repr.

    No object-store write, vector upsert, document row, claim row, monitor audit
    row, discovery mutation, or trust transition occurs here.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")

    source = validate_source_url(source_id, url)
    downloaded, extracted, publication_date = _resolve_preflight_evidence(
        source_id,
        url,
        download=download,
    )

    chunks = chunk_text(
        extracted.text,
        chunk_size=chunk_size,
        overlap=chunk_overlap,
    )
    if not chunks:
        raise ValueError("Preflight document produced no searchable chunks")

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
