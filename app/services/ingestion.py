from uuid import uuid4

from app.core.config import get_settings
from app.ingestion.chunker import chunk_text
from app.ingestion.downloader import download_trusted_document
from app.ingestion.extractor import extract_document
from app.ingestion.quality import validate_extracted_document
from app.storage.database import DocumentRecord, find_document_by_sha, get_session
from app.storage.object_store import put_raw_document
from app.storage.vector_store import index_chunks


def ingest_url(source_id: str, url: str) -> dict[str, object]:
    settings = get_settings()
    downloaded = download_trusted_document(source_id, url)

    with get_session() as session:
        existing = find_document_by_sha(session, downloaded.sha256)
        if existing:
            return {
                "status": "already_indexed",
                "document_id": existing.id,
                "source_id": existing.source_id,
                "title": existing.title,
                "chunk_count": existing.chunk_count,
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
        session.commit()

    return {
        "status": "indexed",
        "document_id": document_id,
        "source_id": source_id,
        "source_name": downloaded.source.name,
        "title": extracted.title,
        "chunk_count": len(chunks),
        "sha256": downloaded.sha256,
        "retrieved_at": downloaded.retrieved_at.isoformat(),
        "object_key": object_key,
    }
