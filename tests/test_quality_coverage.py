from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.quality_coverage_dashboard as quality_api
import app.services.quality_coverage as quality_service
from app.main import app
from app.storage.database import Base, ClaimRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _claim(
    claim_id: str,
    *,
    source_id: str,
    metric: str,
    value_text: str,
    value_numeric: str | None = "5.0",
    publication_date: date | None = date(2026, 9, 17),
    state: str = "candidate",
    evidence: str = "Official source evidence",
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{claim_id}",
        source_id=source_id,
        source_url=f"https://example.test/{claim_id}",
        entity="India",
        metric=metric,
        value_text=value_text,
        value_numeric=Decimal(value_numeric) if value_numeric is not None else None,
        unit="%",
        publication_date=publication_date,
        effective_date=None,
        evidence_text=evidence,
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
        created_at=datetime(2026, 9, 17, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 17, 8, 0, tzinfo=UTC),
    )


def test_quality_coverage_respects_independence_and_quality_filters(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim(
                    "rbi-gdp",
                    source_id="rbi",
                    metric="GDP Growth",
                    value_text="5.0%",
                ),
                _claim(
                    "worldbank-gdp",
                    source_id="world_bank",
                    metric="GDP Growth",
                    value_text="5.0%",
                ),
                _claim(
                    "noise",
                    source_id="rbi",
                    metric="Posted On",
                    value_text="17",
                    value_numeric="17",
                ),
                _claim(
                    "undated",
                    source_id="imf",
                    metric="Inflation Rate",
                    value_text="4.0%",
                    value_numeric="4.0",
                    publication_date=None,
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(quality_service, "get_session", lambda: Session())
    result = quality_service.build_quality_coverage_snapshot(limit=100)

    assert result["summary"]["claims_total"] == 4
    assert result["summary"]["quality_failed_claims"] == 1
    assert result["summary"]["missing_temporal_scope"] == 1
    assert result["summary"]["independently_supported_groups"] == 1
    assert result["summary"]["single_independence_group_groups"] == 0
    assert result["quality_reason_counts"] == {"metadata_metric": 1}
    assert result["coverage_groups"][0]["coverage_status"] == "independently_supported_same_value"
    assert result["coverage_groups"][0]["independence_group_count"] == 2
    assert result["missing_temporal_items"][0]["claim_id"] == "undated"


def test_quality_coverage_surfaces_independent_value_conflict(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim("rbi", source_id="rbi", metric="GDP Growth", value_text="5.0%"),
                _claim(
                    "imf",
                    source_id="imf",
                    metric="GDP Growth",
                    value_text="6.0%",
                    value_numeric="6.0",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(quality_service, "get_session", lambda: Session())
    result = quality_service.build_quality_coverage_snapshot(limit=100)

    assert result["summary"]["independent_conflict_groups"] == 1
    assert result["coverage_groups"][0]["coverage_status"] == "independent_values_disagree"
    assert result["coverage_groups"][0]["distinct_values"] == 2


def test_quality_coverage_routes_are_protected_and_read_only(monkeypatch) -> None:
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
        quality_api,
        "build_quality_coverage_snapshot",
        lambda **kwargs: {
            "generated_at": "2026-09-17T08:00:00+00:00",
            "summary": {"claims_total": 40},
            "per_source": [],
            "coverage_groups": [],
            "missing_temporal_items": [],
            "safety": {"note": "read-only"},
            "scope": kwargs,
        },
    )

    assert client.get("/dashboard/quality-coverage").status_code == 401
    page = client.get("/dashboard/quality-coverage", auth=("operator", "secret"))
    status = client.get(
        "/dashboard/quality-coverage/status?limit=50",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Claim Quality & Verification Coverage" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["summary"]["claims_total"] == 40
