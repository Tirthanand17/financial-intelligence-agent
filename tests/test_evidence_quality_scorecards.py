from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.evidence_quality_scorecards_dashboard as scorecard_api
import app.services.evidence_quality_scorecards as scorecard_service
from app.main import app
from app.storage.database import Base, ClaimEntityAttributionRecord, ClaimRecord, DocumentRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_scorecards_report_dimensions_without_composite_truth_score(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add(
            DocumentRecord(
                id="doc-score",
                source_id="rbi",
                source_name="Reserve Bank of India",
                source_url="https://example.test/source",
                final_url="https://example.test/document.pdf",
                title="Policy Decision",
                content_type="application/pdf",
                sha256="a" * 64,
                object_key="private/doc-score.pdf",
                retrieved_at=datetime(2026, 9, 18, 1, 0, tzinfo=UTC),
                chunk_count=2,
                status="indexed",
            )
        )
        session.add(
            ClaimRecord(
                id="claim-score",
                fingerprint="b" * 64,
                document_id="doc-score",
                source_id="rbi",
                source_url="https://example.test/document.pdf",
                entity="Reserve Bank of India",
                metric="Repo Rate",
                value_text="5.50%",
                value_numeric=Decimal("5.50"),
                unit="%",
                publication_date=date(2026, 9, 18),
                effective_date=None,
                evidence_text="The repo rate is 5.50 per cent.",
                evidence_chunk_index=1,
                confidence=0.98,
                state="candidate",
                created_at=datetime(2026, 9, 18, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 9, 18, 1, 1, tzinfo=UTC),
            )
        )
        session.add(
            ClaimEntityAttributionRecord(
                claim_id="claim-score",
                canonical_entity="Reserve Bank of India",
                source_default_entity="Reserve Bank of India",
                basis="source_default",
                matched_aliases="[]",
                ambiguous_candidates="[]",
                evidence_text="The repo rate is 5.50 per cent.",
                created_at=datetime(2026, 9, 18, 1, 1, tzinfo=UTC),
            )
        )
        session.commit()

    monkeypatch.setattr(scorecard_service, "get_session", lambda: Session())
    result = scorecard_service.build_evidence_quality_scorecards()

    assert result["overall"]["claims_total"] == 1
    for dimension in (
        "quality_gate_pass",
        "temporal_scope_present",
        "entity_attribution_recorded",
        "linked_document_present",
        "document_sha_present",
        "raw_evidence_reference_present",
        "source_registry_known",
        "indicator_catalog_mapped",
    ):
        assert result["overall"]["dimensions"][dimension]["present"] == 1
        assert result["overall"]["dimensions"][dimension]["percent_present"] == 100.0
    assert result["interpretation"]["composite_score"] is None
    assert result["interpretation"]["truth_probability"] is None
    assert result["interpretation"]["ranking"] is False
    assert result["safety"]["exposes_object_keys"] is False
    assert "object_key" not in str(result)


def test_scorecards_keep_unmapped_indicator_informational_not_invalid(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add(
            ClaimRecord(
                id="claim-unmapped",
                fingerprint="c" * 64,
                document_id="missing-doc",
                source_id="rbi",
                source_url="https://example.test/unmapped",
                entity="Reserve Bank of India",
                metric="Custom Official Metric",
                value_text="10",
                value_numeric=Decimal("10"),
                unit="units",
                publication_date=None,
                effective_date=None,
                evidence_text="Custom Official Metric is 10 units.",
                evidence_chunk_index=0,
                confidence=0.8,
                state="candidate",
                created_at=datetime(2026, 9, 18, 1, 2, tzinfo=UTC),
                updated_at=datetime(2026, 9, 18, 1, 2, tzinfo=UTC),
            )
        )
        session.commit()

    monkeypatch.setattr(scorecard_service, "get_session", lambda: Session())
    result = scorecard_service.build_evidence_quality_scorecards()

    assert result["overall"]["dimensions"]["indicator_catalog_mapped"]["missing"] == 1
    assert "unmapped source metric can still be valid evidence" in result["interpretation"]["note"]
    assert "indicator_catalog_mapped" in result["issue_examples"][0]["missing_dimensions"]


def test_scorecard_routes_are_private_read_only_and_no_store(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type("Settings", (), {"dashboard_username": "operator", "dashboard_password": "secret"})(),
    )
    monkeypatch.setattr(
        scorecard_api,
        "build_evidence_quality_scorecards",
        lambda: {
            "generated_at": "2026-09-18T02:00:00+00:00",
            "overall": {"claims_total": 0, "claims_active": 0, "dimensions": {}},
            "per_source": [],
            "issue_examples": [],
            "interpretation": {"note": "no truth score", "composite_score": None},
            "safety": {"read_only": True, "exposes_object_keys": False},
        },
    )

    assert client.get("/dashboard/quality-scorecards").status_code == 401
    page = client.get("/dashboard/quality-scorecards", auth=("operator", "secret"))
    status_response = client.get(
        "/dashboard/quality-scorecards/status",
        auth=("operator", "secret"),
    )
    assert page.status_code == 200
    assert "Evidence Quality Scorecards" in page.text
    lowered = page.text.lower()
    assert "/ingest" not in lowered
    assert "method=\"post\"" not in lowered
    assert status_response.status_code == 200
    assert status_response.headers["cache-control"] == "no-store"
