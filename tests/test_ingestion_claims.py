from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

import app.services.ingestion as ingestion_service
from app.ingestion.downloader import DownloadedDocument
from app.sources.registry import AuthorityLevel, SourceDefinition
from app.storage.database import Base, ClaimRecord


CONTENT = b"Policy Repo Rate : 5.25%\nBase Rate : 8.40% - 10.00%"
SOURCE_URL = "https://www.rbi.org.in/"


def _downloaded() -> DownloadedDocument:
    source = SourceDefinition(
        source_id="rbi",
        name="Reserve Bank of India",
        base_url=SOURCE_URL,
        allowed_hosts=("www.rbi.org.in",),
        category="central_bank",
        authority_level=AuthorityLevel.A,
        country="IN",
    )
    return DownloadedDocument(
        source=source,
        source_url=SOURCE_URL,
        final_url=SOURCE_URL,
        content=CONTENT,
        content_type="text/plain",
        sha256=sha256(CONTENT).hexdigest(),
        retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def _configure_isolated_ingestion(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(ingestion_service, "get_session", lambda: Session(engine))
    monkeypatch.setattr(
        ingestion_service,
        "get_settings",
        lambda: SimpleNamespace(chunk_size_chars=3500, chunk_overlap_chars=400),
    )
    monkeypatch.setattr(
        ingestion_service,
        "download_trusted_document",
        lambda source_id, url: _downloaded(),
    )
    monkeypatch.setattr(
        ingestion_service,
        "put_raw_document",
        lambda **kwargs: "raw/rbi/test-evidence.txt",
    )
    monkeypatch.setattr(ingestion_service, "get_raw_document", lambda object_key: CONTENT)
    monkeypatch.setattr(ingestion_service, "index_chunks", lambda **kwargs: None)
    return engine


def test_new_ingestion_persists_candidate_claims(monkeypatch) -> None:
    engine = _configure_isolated_ingestion(monkeypatch)

    result = ingestion_service.ingest_url("rbi", SOURCE_URL)

    with Session(engine) as session:
        records = list(session.scalars(select(ClaimRecord).order_by(ClaimRecord.metric)))

    assert result["status"] == "indexed"
    assert result["claim_count"] == 2
    assert result["claims_created"] == 2
    assert len(records) == 2
    assert {record.value_text for record in records} == {"5.25%", "8.40% - 10.00%"}
    assert all(record.state == "candidate" for record in records)
    assert all(record.source_url == SOURCE_URL for record in records)


def test_existing_phase1_document_is_backfilled_idempotently(monkeypatch) -> None:
    engine = _configure_isolated_ingestion(monkeypatch)

    first = ingestion_service.ingest_url("rbi", SOURCE_URL)
    assert first["claims_created"] == 2

    # Simulate a Phase 1 document that exists without any Phase 2 claim rows.
    with Session(engine) as session:
        session.execute(delete(ClaimRecord))
        session.commit()

    backfilled = ingestion_service.ingest_url("rbi", SOURCE_URL)
    repeated = ingestion_service.ingest_url("rbi", SOURCE_URL)

    with Session(engine) as session:
        count = session.scalar(select(func.count()).select_from(ClaimRecord))

    assert backfilled["status"] == "already_indexed"
    assert backfilled["claim_count"] == 2
    assert backfilled["claims_created"] == 2
    assert repeated["status"] == "already_indexed"
    assert repeated["claim_count"] == 2
    assert repeated["claims_created"] == 0
    assert count == 2
