from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.document_detail_dashboard as document_api
import app.services.document_detail as document_detail
from app.main import app
from app.storage.database import (
    Base,
    ClaimEntityAttributionRecord,
    ClaimRecord,
    ClaimVerificationEventRecord,
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
)


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _document() -> DocumentRecord:
    return DocumentRecord(
        id="doc-detail",
        source_id="rbi",
        source_name="Reserve Bank of India",
        source_url="https://example.test/rbi/source",
        final_url="https://example.test/rbi/document.pdf",
        title="Policy Repo Rate Decision",
        content_type="application/pdf",
        sha256="a" * 64,
        object_key="private/rbi/doc-detail.pdf",
        retrieved_at=datetime(2026, 9, 18, 1, 0, tzinfo=UTC),
        chunk_count=3,
        status="indexed",
    )


def _claim() -> ClaimRecord:
    return ClaimRecord(
        id="claim-detail",
        fingerprint="b" * 64,
        document_id="doc-detail",
        source_id="rbi",
        source_url="https://example.test/rbi/document.pdf",
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text="5.50%",
        value_numeric=Decimal("5.50"),
        unit="%",
        publication_date=date(2026, 6, 6),
        effective_date=None,
        evidence_text="The policy repo rate is 5.50 per cent.",
        evidence_chunk_index=1,
        confidence=0.98,
        state="candidate",
        created_at=datetime(2026, 9, 18, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 18, 1, 1, tzinfo=UTC),
    )


def test_document_detail_exposes_audit_provenance_without_object_key(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add(_document())
        session.add(_claim())
        session.add(
            ClaimEntityAttributionRecord(
                claim_id="claim-detail",
                canonical_entity="Reserve Bank of India",
                source_default_entity="Reserve Bank of India",
                basis="source_default",
                matched_aliases='["Reserve Bank of India"]',
                ambiguous_candidates="[]",
                evidence_text="The policy repo rate is 5.50 per cent.",
                created_at=datetime(2026, 9, 18, 1, 1, tzinfo=UTC),
            )
        )
        session.add(
            ClaimVerificationEventRecord(
                id="verification-detail",
                claim_id="claim-detail",
                from_state="candidate",
                to_state="candidate",
                reason="insufficient_independent_sources",
                supporting_source_ids='["rbi"]',
                conflicting_source_ids="[]",
                created_at=datetime(2026, 9, 18, 1, 2, tzinfo=UTC),
            )
        )
        session.add(
            SourceMonitorDiscoveryRecord(
                id="discovery-detail",
                discovery_key="c" * 64,
                item_fingerprint="d" * 64,
                monitor_id="rbi-press-releases-rss",
                source_id="rbi",
                url="https://example.test/rbi/document.pdf",
                title="Policy Repo Rate Decision",
                publication_date=date(2026, 6, 6),
                status="ingested",
                document_id="doc-detail",
                first_seen_at=datetime(2026, 9, 18, 0, 55, tzinfo=UTC),
                last_seen_at=datetime(2026, 9, 18, 0, 56, tzinfo=UTC),
                seen_count=1,
                attempt_count=1,
                last_attempt_at=datetime(2026, 9, 18, 0, 57, tzinfo=UTC),
                last_error_code=None,
            )
        )
        session.commit()

    monkeypatch.setattr(document_detail, "get_session", lambda: Session())
    result = document_detail.build_document_detail("doc-detail")

    assert result is not None
    assert result["document"]["sha256"] == "a" * 64
    assert result["document"]["raw_evidence_retained"] is True
    assert result["document"]["object_reference_redacted"] is True
    assert "object_key" not in result["document"]
    assert result["summary"]["claims"] == 1
    assert result["summary"]["verification_events"] == 1
    assert result["summary"]["discovery_links"] == 1
    claim = result["claims"][0]
    assert claim["indicator_id"] == "policy_repo_rate"
    assert claim["quality_gate"] == "pass"
    assert claim["attribution"]["canonical_entity"] == "Reserve Bank of India"
    assert claim["verification_events"][0]["reason"] == "insufficient_independent_sources"
    assert result["safety"]["exposes_object_keys"] is False
    assert result["safety"]["mutates_data"] is False

    with Session() as session:
        persisted = session.scalar(select(DocumentRecord).where(DocumentRecord.id == "doc-detail"))
        assert persisted is not None
        assert persisted.object_key == "private/rbi/doc-detail.pdf"


def test_document_detail_returns_none_for_unknown_document(monkeypatch) -> None:
    Session = _session_factory()
    monkeypatch.setattr(document_detail, "get_session", lambda: Session())
    assert document_detail.build_document_detail("missing") is None


def test_document_detail_routes_are_private_read_only_and_object_key_free(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )
    monkeypatch.setattr(
        document_api,
        "build_document_detail",
        lambda document_id: {
            "generated_at": "2026-09-18T02:00:00+00:00",
            "mode": "read_only_document_evidence_detail",
            "document": {
                "document_id": document_id,
                "source_id": "rbi",
                "source_name": "Reserve Bank of India",
                "source_url": "https://example.test/rbi",
                "final_url": "https://example.test/rbi/document.pdf",
                "title": "Policy Repo Rate Decision",
                "content_type": "application/pdf",
                "sha256": "a" * 64,
                "retrieved_at": "2026-09-18T01:00:00+00:00",
                "chunk_count": 3,
                "status": "indexed",
                "raw_evidence_retained": True,
                "object_reference_redacted": True,
            },
            "summary": {
                "claims": 0,
                "claim_states": {},
                "quality_failures": 0,
                "verification_events": 0,
                "trust_events": 0,
                "supersession_edges": 0,
                "discovery_links": 0,
            },
            "discoveries": [],
            "claims": [],
            "safety": {
                "read_only": True,
                "mutates_data": False,
                "exposes_object_keys": False,
                "note": "read-only",
            },
        },
    )

    assert client.get("/dashboard/document").status_code == 401
    page = client.get("/dashboard/document", auth=("operator", "secret"))
    status_response = client.get(
        "/dashboard/document/doc-detail/status",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Document Evidence Detail" in page.text
    lowered = page.text.lower()
    assert "/ingest" not in lowered
    assert "method=\"post\"" not in lowered
    assert "trust_promotion_enabled=true" not in lowered
    assert status_response.status_code == 200
    assert status_response.headers["cache-control"] == "no-store"
    payload = status_response.json()
    assert payload["document"]["object_reference_redacted"] is True
    assert "object_key" not in payload["document"]
