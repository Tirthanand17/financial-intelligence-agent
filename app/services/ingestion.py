from datetime import date
from uuid import uuid4

from sqlalchemy.orm import Session

from app.claims.extractor import extract_structured_claims
from app.claims.storage import save_claim
from app.claims.verification_storage import reconcile_verification_for_claim
from app.claims.versioning_storage import apply_supersession_for_newer_claim
from app.core.config import get_settings
from app.ingestion.chunker import chunk_text
from app.ingestion.downloader import download_trusted_document
from app.ingestion.extractor import extract_document
from app.ingestion.quality import validate_extracted_document
from app.sources.metadata import extract_source_publication_date
from app.storage.database import DocumentRecord, find_document_by_sha, get_session
from app.storage.object_store import get_raw_document, put_raw_document
from app.storage.vector_store import index_chunks


def _extract_claim_candidates(
    *,
    chunks: list[str],
    document_id: str,
    source_id: str,
    source_url: str,
    entity: str,
    publication_date: date | None = None,
):
    return extract_structured_claims(
        chunks=chunks,
        document_id=document_id,
        source_id=source_id,
        source_url=source_url,
        entity=entity,
        publication_date=publication_date,
    )


def _stage_claims(session: Session, claims) -> tuple[int, int, int]:
    """Persist claims, version history, and verification in one transaction.

    Supersession is applied before cross-source verification so obsolete
    source-local versions cannot be counted as active corroborating evidence.
    Both steps are attempted for newly created and already-known claims, making
    ingestion backward-compatible and idempotent for older data.

    TRUSTED promotion is still intentionally not automatic here. Phase 4 first
    validates real dated cross-source evidence before trust reconciliation is
    enabled in the normal ingestion path.
    """
    created_count = 0
    supersessions_created = 0
    verification_events_created = 0

    for claim in claims:
        record, created = save_claim(session, claim, commit=False)
        if created:
            created_count += 1

        supersession_audits = apply_supersession_for_newer_claim(
            session,
            record,
            commit=False,
        )
        supersessions_created += len(supersession_audits)

        verification_events = reconcile_verification_for_claim(
            session,
            record,
            commit=False,
        )
        verification_events_created += len(verification_events)

    return created_count, supersessions_created, verification_events_created


def _backfill_existing_document_claims(
    session: Session,
    record: DocumentRecord,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[int, int, int, int]:
    """Idempotently derive claims for an already preserved document.

    Existing raw evidence is reread from private object storage rather than
    downloading the public source again. This preserves the exact evidence that
    was originally accepted and lets previously indexed documents gain newer
    structured-claim capabilities safely.
    """
    content = get_raw_document(record.object_key)
    extracted = extract_document(content, record.content_type)
    validate_extracted_document(extracted, record.content_type)
    chunks = chunk_text(
        extracted.text,
        chunk_size=chunk_size,
        overlap=chunk_overlap,
    )
    if not chunks:
        raise ValueError("Stored document produced no searchable chunks during claim backfill")

    publication_date = extract_source_publication_date(record.source_id, extracted.text)
    claims = _extract_claim_candidates(
        chunks=chunks,
        document_id=record.id,
        source_id=record.source_id,
        source_url=record.final_url,
        entity=record.source_name,
        publication_date=publication_date,
    )
    (
        created_count,
        supersessions_created,
        verification_events_created,
    ) = _stage_claims(session, claims)
    session.commit()
    return (
        len(claims),
        created_count,
        supersessions_created,
        verification_events_created,
    )


def ingest_url(source_id: str, url: str) -> dict[str, object]:
    settings = get_settings()
    downloaded = download_trusted_document(source_id, url)

    with get_session() as session:
        existing = find_document_by_sha(session, downloaded.sha256)
        if existing:
            (
                claim_count,
                claims_created,
                supersessions_created,
                verification_events_created,
            ) = _backfill_existing_document_claims(
                session,
                existing,
                chunk_size=settings.chunk_size_chars,
                chunk_overlap=settings.chunk_overlap_chars,
            )
            return {
                "status": "already_indexed",
                "document_id": existing.id,
                "source_id": existing.source_id,
                "title": existing.title,
                "chunk_count": existing.chunk_count,
                "claim_count": claim_count,
                "claims_created": claims_created,
                "supersessions_created": supersessions_created,
                "verification_events_created": verification_events_created,
                "sha256": existing.sha256,
            }

        extracted = extract_document(downloaded.content, downloaded.content_type)
        validate_extracted_document(extracted, downloaded.content_type)

        chunks = chunk_text(
            extracted.text,
            chunk_size=settings.chunk_size_chars,
            overlap=settings.chunk_overlap_chars,
        )
        if not chunks:
            raise ValueError("Document produced no searchable chunks")

        document_id = str(uuid4())
        publication_date = extract_source_publication_date(source_id, extracted.text)
        claims = _extract_claim_candidates(
            chunks=chunks,
            document_id=document_id,
            source_id=source_id,
            source_url=downloaded.final_url,
            entity=downloaded.source.name,
            publication_date=publication_date,
        )

        object_key = put_raw_document(
            source_id=source_id,
            sha256=downloaded.sha256,
            content=downloaded.content,
            content_type=downloaded.content_type,
        )

        payload_base: dict[str, object] = {
            "source_id": source_id,
            "source_name": downloaded.source.name,
            "source_url": downloaded.source_url,
            "final_url": downloaded.final_url,
            "title": extracted.title or "",
            "sha256": downloaded.sha256,
            "retrieved_at": downloaded.retrieved_at.isoformat(),
            "authority_level": downloaded.source.authority_level.value,
        }
        index_chunks(
            document_id=document_id,
            chunks=chunks,
            payload_base=payload_base,
        )

        record = DocumentRecord(
            id=document_id,
            source_id=source_id,
            source_name=downloaded.source.name,
            source_url=downloaded.source_url,
            final_url=downloaded.final_url,
            title=extracted.title,
            content_type=downloaded.content_type,
            sha256=downloaded.sha256,
            object_key=object_key,
            retrieved_at=downloaded.retrieved_at,
            chunk_count=len(chunks),
            status="indexed",
        )
        session.add(record)
        (
            claims_created,
            supersessions_created,
            verification_events_created,
        ) = _stage_claims(session, claims)
        session.commit()

    return {
        "status": "indexed",
        "document_id": document_id,
        "source_id": source_id,
        "source_name": downloaded.source.name,
        "title": extracted.title,
        "chunk_count": len(chunks),
        "claim_count": len(claims),
        "claims_created": claims_created,
        "supersessions_created": supersessions_created,
        "verification_events_created": verification_events_created,
        "sha256": downloaded.sha256,
        "retrieved_at": downloaded.retrieved_at.isoformat(),
        "object_key": object_key,
    }
