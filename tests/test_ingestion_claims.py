from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

import app.services.ingestion as ingestion_service
from app.ingestion.downloader import DownloadedDocument
from app.sources.registry import AuthorityLevel, SourceDefinition
from app.storage.database import (
    Base,
    ClaimRecord,
    ClaimSupersessionRecord,
    ClaimVerificationEventRecord,
)


CONTENT = b"Policy Repo Rate : 5.25%\nBase Rate : 8.40% - 10.00%"
SOURCE_URL = "https://www.rbi.org.in/"


def _source(
    *,
    source_id: str = "rbi",
    name: str = "Reserve Bank of India",
    url: str = SOURCE_URL,
    authority_level: AuthorityLevel = AuthorityLevel.A,
) -> SourceDefinition:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    return SourceDefinition(
        source_id=source_id,
        name=name,
        base_url=url,
        allowed_hosts=(host,),
        category="test_financial_source",
        authority_level=authority_level,
        country="IN",
    )


def _downloaded(
    content: bytes = CONTENT,
    *,
    source_id: str = "rbi",
    name: str = "Reserve Bank of India",
    url: str = SOURCE_URL,
    authority_level: AuthorityLevel = AuthorityLevel.A,
) -> DownloadedDocument:
    return DownloadedDocument(
        source=_source(
            source_id=source_id,
            name=name,
            url=url,
            authority_level=authority_level,
        ),
        source_url=url,
        final_url=url,
        content=content,
        content_type="text/plain",
        sha256=sha256(content).hexdigest(),
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
    assert result["supersessions_created"] == 0
    assert result["verification_events_created"] == 0
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
    assert backfilled["supersessions_created"] == 0
    assert backfilled["verification_events_created"] == 0
    assert repeated["status"] == "already_indexed"
    assert repeated["claim_count"] == 2
    assert repeated["claims_created"] == 0
    assert repeated["supersessions_created"] == 0
    assert repeated["verification_events_created"] == 0
    assert count == 2


def test_newer_dated_ingestion_supersedes_older_claim_and_preserves_history(monkeypatch) -> None:
    engine = _configure_isolated_ingestion(monkeypatch)

    older_content = b"Effective Date\n2026-01-01\nPolicy Repo Rate : 5.50%"
    newer_content = b"Effective Date\n2026-02-01\nPolicy Repo Rate : 5.25%"
    downloads = iter((_downloaded(older_content), _downloaded(newer_content)))

    monkeypatch.setattr(
        ingestion_service,
        "download_trusted_document",
        lambda source_id, url: next(downloads),
    )

    first = ingestion_service.ingest_url("rbi", SOURCE_URL)
    second = ingestion_service.ingest_url("rbi", SOURCE_URL)

    with Session(engine) as session:
        claims = list(
            session.scalars(
                select(ClaimRecord)
                .where(ClaimRecord.metric == "Policy Repo Rate")
                .order_by(ClaimRecord.effective_date)
            )
        )
        audits = list(session.scalars(select(ClaimSupersessionRecord)))

    assert first["claims_created"] == 1
    assert first["supersessions_created"] == 0
    assert first["verification_events_created"] == 0
    assert second["claims_created"] == 1
    assert second["supersessions_created"] == 1
    assert second["verification_events_created"] == 0

    assert len(claims) == 2
    assert claims[0].value_text == "5.50%"
    assert claims[0].state == "superseded"
    assert claims[1].value_text == "5.25%"
    assert claims[1].state == "candidate"

    assert len(audits) == 1
    assert audits[0].older_claim_id == claims[0].id
    assert audits[0].newer_claim_id == claims[1].id
    assert audits[0].newer_document_id == claims[1].document_id


def test_reingesting_known_newer_claim_does_not_duplicate_supersession(monkeypatch) -> None:
    engine = _configure_isolated_ingestion(monkeypatch)

    older_content = b"Effective Date\n2026-01-01\nPolicy Repo Rate : 5.50%"
    newer_content = b"Effective Date\n2026-02-01\nPolicy Repo Rate : 5.25%"
    downloaded_older = _downloaded(older_content)
    downloaded_newer = _downloaded(newer_content)
    downloads = iter((downloaded_older, downloaded_newer, downloaded_newer))

    monkeypatch.setattr(
        ingestion_service,
        "download_trusted_document",
        lambda source_id, url: next(downloads),
    )
    monkeypatch.setattr(
        ingestion_service,
        "get_raw_document",
        lambda object_key: newer_content,
    )

    ingestion_service.ingest_url("rbi", SOURCE_URL)
    ingestion_service.ingest_url("rbi", SOURCE_URL)
    repeated = ingestion_service.ingest_url("rbi", SOURCE_URL)

    with Session(engine) as session:
        audit_count = session.scalar(
            select(func.count()).select_from(ClaimSupersessionRecord)
        )

    assert repeated["status"] == "already_indexed"
    assert repeated["claims_created"] == 0
    assert repeated["supersessions_created"] == 0
    assert repeated["verification_events_created"] == 0
    assert audit_count == 1


def test_ingestion_reconciles_independent_agreement_in_same_temporal_scope(monkeypatch) -> None:
    engine = _configure_isolated_ingestion(monkeypatch)

    content_a = b"Effective Date\n2026-09-12\nPolicy Repo Rate : 5.25%"
    content_b = b"Effective Date\n2026-09-12\nPolicy Repo Rate : 5.25%\nSource Copy : 1%"
    downloads = iter(
        (
            _downloaded(content_a, source_id="source-a", name="Reserve Bank of India"),
            _downloaded(content_b, source_id="source-b", name="Reserve Bank of India"),
        )
    )
    monkeypatch.setattr(
        ingestion_service,
        "download_trusted_document",
        lambda source_id, url: next(downloads),
    )

    first = ingestion_service.ingest_url("source-a", "https://source-a.test/")
    second = ingestion_service.ingest_url("source-b", "https://source-b.test/")

    with Session(engine) as session:
        repo_claims = list(
            session.scalars(
                select(ClaimRecord)
                .where(ClaimRecord.metric == "Policy Repo Rate")
                .order_by(ClaimRecord.source_id)
            )
        )
        event_count = session.scalar(
            select(func.count()).select_from(ClaimVerificationEventRecord)
        )

    assert first["verification_events_created"] == 0
    assert second["verification_events_created"] == 2
    assert [record.state for record in repo_claims] == ["verified", "verified"]
    assert event_count == 2


def test_ingestion_reconciles_independent_disagreement_as_conflict(monkeypatch) -> None:
    engine = _configure_isolated_ingestion(monkeypatch)

    content_a = b"Effective Date\n2026-09-12\nPolicy Repo Rate : 5.25%"
    content_b = b"Effective Date\n2026-09-12\nPolicy Repo Rate : 5.50%"
    downloads = iter(
        (
            _downloaded(content_a, source_id="source-a", name="Reserve Bank of India"),
            _downloaded(content_b, source_id="source-b", name="Reserve Bank of India"),
        )
    )
    monkeypatch.setattr(
        ingestion_service,
        "download_trusted_document",
        lambda source_id, url: next(downloads),
    )

    ingestion_service.ingest_url("source-a", "https://source-a.test/")
    second = ingestion_service.ingest_url("source-b", "https://source-b.test/")

    with Session(engine) as session:
        repo_claims = list(
            session.scalars(
                select(ClaimRecord)
                .where(ClaimRecord.metric == "Policy Repo Rate")
                .order_by(ClaimRecord.source_id)
            )
        )
        events = list(session.scalars(select(ClaimVerificationEventRecord)))

    assert second["verification_events_created"] == 2
    assert [record.state for record in repo_claims] == ["conflicted", "conflicted"]
    assert len(events) == 2
    assert {event.reason for event in events} == {"independent_sources_disagree"}
