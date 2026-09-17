from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.evidence_search_dashboard as search_api
import app.services.evidence_search as evidence_search
from app.main import app
from app.storage.database import Base, ClaimRecord, DocumentRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _document(document_id: str, *, source_id: str = "rbi", title: str = "Monetary Policy") -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        source_id=source_id,
        source_name="Reserve Bank of India" if source_id == "rbi" else source_id.upper(),
        source_url=f"https://example.test/{document_id}",
        final_url=f"https://example.test/{document_id}.pdf",
        title=title,
        content_type="application/pdf",
        sha256=(document_id * 64)[:64],
        object_key=f"private/{document_id}.pdf",
        retrieved_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
        chunk_count=2,
        status="indexed",
    )


def _claim(
    claim_id: str,
    document_id: str,
    *,
    source_id: str = "rbi",
    metric: str = "Policy Repo Rate",
    value_text: str = "5.50%",
    publication_date: date | None = date(2026, 6, 6),
    effective_date: date | None = None,
    state: str = "candidate",
    evidence_text: str = "The policy repo rate is 5.50 per cent.",
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=document_id,
        source_id=source_id,
        source_url=f"https://example.test/{document_id}",
        entity="Reserve Bank of India",
        metric=metric,
        value_text=value_text,
        value_numeric=Decimal("5.50"),
        unit="%",
        publication_date=publication_date,
        effective_date=effective_date,
        evidence_text=evidence_text,
        evidence_chunk_index=0,
        confidence=0.97,
        state=state,
        created_at=datetime(2026, 9, 17, 5, 5, tzinfo=UTC),
        updated_at=datetime(2026, 9, 17, 5, 5, tzinfo=UTC),
    )


def test_search_returns_claim_with_linked_document_and_exact_catalog_overlay(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add(_document("doc-one", title="Policy Repo Rate Decision"))
        session.add(_claim("claim-one", "doc-one"))
        session.commit()

    monkeypatch.setattr(evidence_search, "get_session", lambda: Session())
    result = evidence_search.build_evidence_search_snapshot(q="repo rate", source_id="rbi")

    assert result["summary"]["claim_hits"] == 1
    assert result["summary"]["document_hits"] == 1
    claim = result["claims"][0]
    assert claim["indicator_id"] == "policy_repo_rate"
    assert claim["canonical_metric"] == "Policy Repo Rate"
    assert claim["normalization_basis"] == "exact_catalog_alias"
    assert claim["document"]["sha256"] == ("doc-one" * 64)[:64]
    assert "object_key" not in claim["document"]
    assert result["safety"]["network_crawling"] is False
    assert result["safety"]["exposes_object_keys"] is False


def test_date_filters_use_effective_date_then_publication_without_inventing_dates(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _document("doc-effective"),
                _document("doc-publication"),
                _document("doc-undated"),
                _claim(
                    "effective",
                    "doc-effective",
                    publication_date=date(2026, 5, 1),
                    effective_date=date(2026, 7, 1),
                ),
                _claim(
                    "publication",
                    "doc-publication",
                    publication_date=date(2026, 6, 15),
                    effective_date=None,
                ),
                _claim(
                    "undated",
                    "doc-undated",
                    publication_date=None,
                    effective_date=None,
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(evidence_search, "get_session", lambda: Session())
    result = evidence_search.build_evidence_search_snapshot(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 7, 31),
    )

    assert result["summary"]["claim_hits"] == 2
    by_id = {item["claim_id"]: item for item in result["claims"]}
    assert by_id["effective"]["temporal_date"] == "2026-07-01"
    assert by_id["effective"]["temporal_basis"] == "effective_date"
    assert by_id["publication"]["temporal_date"] == "2026-06-15"
    assert by_id["publication"]["temporal_basis"] == "publication_date"
    assert "undated" not in by_id
    assert result["safety"]["invented_dates"] is False
    assert result["safety"]["uses_retrieval_time_as_publication_date"] is False


def test_claim_filters_are_bounded_and_do_not_mutate_persisted_rows(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add(_document("doc-filter"))
        session.add(
            _claim(
                "claim-filter",
                "doc-filter",
                state="verified",
                metric="Repo Rate",
                evidence_text="Repo Rate: 5.50%",
            )
        )
        session.commit()

    monkeypatch.setattr(evidence_search, "get_session", lambda: Session())
    result = evidence_search.build_evidence_search_snapshot(
        state="verified",
        entity="reserve bank",
        metric="repo",
        limit=10,
        offset=0,
    )

    assert result["summary"]["claim_hits"] == 1
    assert result["claims"][0]["state"] == "verified"
    assert result["claims"][0]["quality_gate"] == "pass"
    assert result["search_contract"]["claim_only_filters_active"] is True
    assert result["safety"]["mutates_data"] is False

    with Session() as session:
        persisted = session.scalar(select(ClaimRecord).where(ClaimRecord.id == "claim-filter"))
        assert persisted is not None
        assert persisted.state == "verified"
        document = session.scalar(select(DocumentRecord).where(DocumentRecord.id == "doc-filter"))
        assert document is not None
        assert document.object_key == "private/doc-filter.pdf"


def test_search_routes_are_private_read_only_and_validate_date_range(monkeypatch) -> None:
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
        search_api,
        "build_evidence_search_snapshot",
        lambda **kwargs: {
            "generated_at": "2026-09-17T12:00:00+00:00",
            "scope": kwargs,
            "summary": {
                "claim_hits": 0,
                "document_hits": 0,
                "returned_claims": 0,
                "returned_documents": 0,
            },
            "claims": [],
            "documents": [],
            "search_contract": {"note": "literal persisted search"},
            "safety": {"note": "read-only"},
        },
    )

    assert client.get("/dashboard/search").status_code == 401
    page = client.get("/dashboard/search", auth=("operator", "secret"))
    response = client.get(
        "/dashboard/search/status?q=repo&source_id=rbi&state=candidate&limit=25",
        auth=("operator", "secret"),
    )
    invalid = client.get(
        "/dashboard/search/status?date_from=2026-09-10&date_to=2026-09-01",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Evidence Search" in page.text
    lowered = page.text.lower()
    assert "/ingest" not in lowered
    assert "method=\"post\"" not in lowered
    assert "trust_promotion_enabled=true" not in lowered
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["scope"]["q"] == "repo"
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "date_from must be on or before date_to"
