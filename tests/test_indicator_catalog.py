from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.indicator_catalog_dashboard as catalog_api
import app.services.indicator_catalog as catalog_service
from app.claims.catalog import normalize_indicator_metric
from app.main import app
from app.storage.database import Base, ClaimRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _claim(claim_id: str, *, metric: str, unit: str | None = "%") -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{claim_id}",
        source_id="rbi",
        source_url=f"https://www.rbi.org.in/{claim_id}",
        entity="Reserve Bank of India",
        metric=metric,
        value_text="5.25%",
        value_numeric=Decimal("5.25"),
        unit=unit,
        publication_date=date(2026, 9, 17),
        effective_date=None,
        evidence_text=f"{metric}: 5.25%",
        evidence_chunk_index=0,
        confidence=0.95,
        state="candidate",
        created_at=datetime(2026, 9, 17, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 17, 8, 0, tzinfo=UTC),
    )


def test_indicator_catalog_uses_exact_aliases_and_preserves_source_label() -> None:
    mapped = normalize_indicator_metric("  GDP   Growth Rate  ")
    unknown = normalize_indicator_metric("GDP growth projection")

    assert mapped.indicator_id == "real_gdp_growth"
    assert mapped.canonical_metric == "Real GDP Growth"
    assert mapped.source_metric == "GDP Growth Rate"
    assert mapped.basis == "exact_catalog_alias"

    assert unknown.indicator_id is None
    assert unknown.canonical_metric == "GDP growth projection"
    assert unknown.basis == "unmapped_exact"


def test_indicator_catalog_snapshot_is_read_only_overlay(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim("repo", metric="Repo Rate"),
                _claim("gdp", metric="GDP Growth"),
                _claim("unknown", metric="Custom Official Metric", unit="bps"),
            ]
        )
        session.commit()

    monkeypatch.setattr(catalog_service, "get_session", lambda: Session())
    result = catalog_service.build_indicator_catalog_snapshot(limit=100)

    assert result["summary"]["persisted_claims"] == 3
    assert result["summary"]["mapped_claims"] == 2
    assert result["summary"]["unmapped_claims"] == 1
    assert result["safety"]["persists_normalization"] is False
    assert result["safety"]["rewrites_source_metric"] is False
    assert result["safety"]["fuzzy_matching_enabled"] is False

    mappings = {item["claim_id"]: item for item in result["claim_mappings"]}
    assert mappings["repo"]["source_metric"] == "Repo Rate"
    assert mappings["repo"]["canonical_metric"] == "Policy Repo Rate"
    assert mappings["unknown"]["indicator_id"] is None
    assert result["unmapped_metrics"][0]["source_metric"] == "Custom Official Metric"


def test_indicator_catalog_routes_are_protected_and_no_store(monkeypatch) -> None:
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
        catalog_api,
        "build_indicator_catalog_snapshot",
        lambda **kwargs: {
            "generated_at": "2026-09-17T09:00:00+00:00",
            "summary": {
                "catalog_indicators": 17,
                "persisted_claims": 40,
                "mapped_claims": 10,
                "unmapped_claims": 30,
                "observed_indicators": 3,
            },
            "indicators": [],
            "unmapped_metrics": [],
            "claim_mappings": [],
            "safety": {"note": "read-only"},
            "scope": kwargs,
        },
    )

    assert client.get("/dashboard/indicator-catalog").status_code == 401
    page = client.get("/dashboard/indicator-catalog", auth=("operator", "secret"))
    status = client.get(
        "/dashboard/indicator-catalog/status?limit=100",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Economic Indicator Catalog" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["summary"]["persisted_claims"] == 40
