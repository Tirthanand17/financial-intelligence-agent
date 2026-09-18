from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.api.intelligence_digest_dashboard as digest_api
import app.services.intelligence_digest as digest
from app.main import app
from app.storage.database import Base, ClaimRecord, DocumentRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _claim(claim_id: str, *, temporal_date: date | None, state: str = "candidate") -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{claim_id}",
        source_id="rbi",
        source_url=f"https://example.test/{claim_id}",
        entity="Reserve Bank of India",
        metric="Policy Repo Rate",
        value_text="5.50%",
        value_numeric=Decimal("5.50"),
        unit="%",
        publication_date=temporal_date,
        effective_date=None,
        evidence_text="Policy Repo Rate: 5.50%",
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
        created_at=datetime(2026, 9, 18, 2, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 18, 2, 0, tzinfo=UTC),
    )


def test_digest_is_bounded_factual_and_preserves_missing_dates(monkeypatch) -> None:
    Session = _session_factory()
    now = datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
    with Session() as session:
        session.add_all(
            [
                DocumentRecord(
                    id="doc-recent",
                    source_id="rbi",
                    source_name="Reserve Bank of India",
                    source_url="https://example.test/recent",
                    final_url="https://example.test/recent",
                    title="Recent RBI release",
                    content_type="text/html",
                    sha256="a" * 64,
                    object_key="private/recent",
                    retrieved_at=datetime(2026, 9, 18, 1, 0, tzinfo=UTC),
                    chunk_count=2,
                    status="indexed",
                ),
                DocumentRecord(
                    id="doc-old",
                    source_id="rbi",
                    source_name="Reserve Bank of India",
                    source_url="https://example.test/old",
                    final_url="https://example.test/old",
                    title="Old RBI release",
                    content_type="text/html",
                    sha256="b" * 64,
                    object_key="private/old",
                    retrieved_at=datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
                    chunk_count=1,
                    status="indexed",
                ),
                _claim("recent", temporal_date=date(2026, 9, 18)),
                _claim("old", temporal_date=date(2026, 9, 1)),
                _claim("undated", temporal_date=None),
            ]
        )
        session.commit()

    monkeypatch.setattr(digest, "get_session", lambda: Session())
    monkeypatch.setattr(
        digest,
        "build_change_detection_snapshot",
        lambda limit=500: {
            "changes": [
                {
                    "change_kind": "numeric_value_change",
                    "entity": "Reserve Bank of India",
                    "canonical_metric": "Policy Repo Rate",
                    "previous": {"value_text": "6.00%"},
                    "current": {
                        "value_text": "5.50%",
                        "temporal_date": "2026-09-18",
                        "source_id": "rbi",
                    },
                    "direction": "decrease",
                },
                {
                    "change_kind": "numeric_value_change",
                    "entity": "Reserve Bank of India",
                    "canonical_metric": "Policy Repo Rate",
                    "previous": {"value_text": "6.50%"},
                    "current": {
                        "value_text": "6.00%",
                        "temporal_date": "2026-08-01",
                        "source_id": "rbi",
                    },
                    "direction": "decrease",
                },
            ]
        },
    )
    monkeypatch.setattr(
        digest,
        "build_incident_snapshot",
        lambda: {
            "status": "clear",
            "summary": {"incidents": 0, "critical": 0, "high": 0},
            "incidents": [],
        },
    )

    result = digest.build_intelligence_digest(lookback_days=3, limit=10, now=now)

    assert result["summary"]["recent_documents"] == 1
    assert result["summary"]["new_quality_safe_active_claims"] == 1
    assert result["summary"]["detected_changes"] == 1
    assert result["recent_documents"][0]["document_id"] == "doc-recent"
    assert result["new_evidence"][0]["claim_id"] == "recent"
    assert result["changes"][0]["current"]["temporal_date"] == "2026-09-18"
    assert result["safety"]["invented_dates"] is False
    assert result["safety"]["mutates_data"] is False
    assert result["safety"]["invokes_language_model"] is False
    assert result["safety"]["sends_external_notifications"] is False


def test_digest_rejects_unbounded_ranges(monkeypatch) -> None:
    Session = _session_factory()
    monkeypatch.setattr(digest, "get_session", lambda: Session())
    monkeypatch.setattr(digest, "build_change_detection_snapshot", lambda limit=500: {"changes": []})
    monkeypatch.setattr(
        digest,
        "build_incident_snapshot",
        lambda: {
            "status": "clear",
            "summary": {"incidents": 0, "critical": 0, "high": 0},
            "incidents": [],
        },
    )

    for kwargs in (
        {"lookback_days": 0},
        {"lookback_days": 31},
        {"limit": 0},
        {"limit": 51},
    ):
        try:
            digest.build_intelligence_digest(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")


def test_digest_routes_reuse_dashboard_auth_and_are_read_only(monkeypatch) -> None:
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
        digest_api,
        "build_intelligence_digest",
        lambda **kwargs: {
            "generated_at": "2026-09-18T03:00:00+00:00",
            "window": kwargs,
            "summary": {
                "recent_documents": 0,
                "new_quality_safe_active_claims": 0,
                "detected_changes": 0,
                "conflicted_claims": 0,
                "operator_incidents": 0,
                "critical_incidents": 0,
                "high_incidents": 0,
            },
            "recent_documents": [],
            "new_evidence": [],
            "changes": [],
            "conflicts": [],
            "incidents": [],
            "incident_status": "clear",
            "safety": {"note": "read-only"},
        },
    )

    assert client.get("/dashboard/digest").status_code == 401
    page = client.get("/dashboard/digest", auth=("operator", "secret"))
    status = client.get(
        "/dashboard/digest/status?lookback_days=7&limit=20",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Financial Intelligence Digest" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["window"] == {"lookback_days": 7, "limit": 20}
