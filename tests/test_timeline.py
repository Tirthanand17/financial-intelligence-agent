from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.timeline_dashboard as timeline_api
import app.services.timeline as timeline
from app.main import app
from app.storage.database import Base, ClaimRecord, ClaimSupersessionRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _claim(
    claim_id: str,
    *,
    value: str,
    numeric: str,
    state: str,
    publication_date: date | None,
    effective_date: date | None = None,
    source_id: str = "rbi",
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{claim_id}",
        source_id=source_id,
        source_url=f"https://example.test/{claim_id}",
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text=value,
        value_numeric=Decimal(numeric),
        unit="%",
        publication_date=publication_date,
        effective_date=effective_date,
        evidence_text=f"Official Policy Repo Rate: {value}",
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
        created_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
    )


def test_timeline_preserves_dates_states_and_supersession_without_mutation(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim(
                    "old",
                    value="6.00%",
                    numeric="6.00",
                    state="superseded",
                    publication_date=date(2026, 6, 1),
                ),
                _claim(
                    "new",
                    value="5.50%",
                    numeric="5.50",
                    state="verified",
                    publication_date=date(2026, 8, 1),
                    effective_date=date(2026, 8, 2),
                ),
                _claim(
                    "undated",
                    value="5.50%",
                    numeric="5.50",
                    state="candidate",
                    publication_date=None,
                ),
                ClaimSupersessionRecord(
                    older_claim_id="old",
                    newer_claim_id="new",
                    newer_document_id="doc-new",
                    temporal_kind="publication",
                    older_date=date(2026, 6, 1),
                    newer_date=date(2026, 8, 1),
                    created_at=datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(timeline, "get_session", lambda: Session())
    result = timeline.build_timeline_snapshot(
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        series_limit=10,
        points_per_series=10,
    )

    assert result["summary"]["claims_in_scope"] == 3
    assert result["summary"]["series_in_scope"] == 1
    assert result["summary"]["undated_claims"] == 1
    assert result["safety"]["invented_dates"] is False
    assert result["safety"]["mutates_data"] is False

    series = result["series"][0]
    assert series["latest_temporal_date"] == "2026-08-02"
    assert series["latest_active"]["claim_id"] == "new"
    points = {point["claim_id"]: point for point in series["points"]}
    assert points["old"]["temporal_basis"] == "publication_date"
    assert points["old"]["superseded_by_claim_id"] == "new"
    assert points["new"]["temporal_basis"] == "effective_date"
    assert points["new"]["supersedes_claim_ids"] == ["old"]
    assert points["undated"]["temporal_date"] is None
    assert points["undated"]["temporal_basis"] == "undated"

    with Session() as session:
        states = {row.id: row.state for row in session.scalars(select(ClaimRecord))}
        assert states == {"old": "superseded", "new": "verified", "undated": "candidate"}


def test_timeline_source_filter_does_not_relabel_evidence(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim(
                    "rbi-one",
                    value="5.50%",
                    numeric="5.50",
                    state="candidate",
                    publication_date=date(2026, 9, 1),
                    source_id="rbi",
                ),
                _claim(
                    "sebi-one",
                    value="5.50%",
                    numeric="5.50",
                    state="candidate",
                    publication_date=date(2026, 9, 1),
                    source_id="sebi",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(timeline, "get_session", lambda: Session())
    result = timeline.build_timeline_snapshot(source_id="rbi")

    assert result["summary"]["claims_in_scope"] == 1
    assert result["series"][0]["points"][0]["source_id"] == "rbi"
    assert {item["source_id"] for item in result["facets"]["sources"]} == {"rbi", "sebi"}


def test_timeline_routes_reuse_dashboard_auth_and_are_read_only(monkeypatch) -> None:
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
        timeline_api,
        "build_timeline_snapshot",
        lambda **kwargs: {
            "generated_at": "2026-09-17T07:00:00+00:00",
            "scope": kwargs,
            "summary": {
                "claims_in_scope": 0,
                "series_in_scope": 0,
                "series_returned": 0,
                "quality_safe_claims": 0,
                "undated_claims": 0,
                "conflicted_claims": 0,
            },
            "state_counts": {},
            "facets": {"entities": [], "metrics": [], "sources": []},
            "series": [],
            "safety": {"note": "read-only"},
        },
    )

    assert client.get("/dashboard/timeline").status_code == 401
    page = client.get("/dashboard/timeline", auth=("operator", "secret"))
    status = client.get(
        "/dashboard/timeline/status?source_id=rbi&series_limit=10&points_per_series=20",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Evidence Timeline Explorer" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert "trading signal" not in page.text.lower() or "not a forecast" in page.text.lower()

    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["scope"] == {
        "entity": None,
        "metric": None,
        "source_id": "rbi",
        "series_limit": 10,
        "points_per_series": 20,
    }
