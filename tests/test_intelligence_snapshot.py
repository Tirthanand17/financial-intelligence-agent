from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.dashboard as dashboard_api
import app.services.intelligence as intelligence
from app.main import app
from app.storage.database import Base, ClaimRecord, DocumentRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _document(document_id: str, source_id: str, retrieved_at: datetime) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        source_id=source_id,
        source_name=source_id.upper(),
        source_url=f"https://example.test/{document_id}",
        final_url=f"https://example.test/{document_id}",
        title=f"Document {document_id}",
        content_type="application/pdf",
        sha256=(document_id * 64)[:64],
        object_key=f"evidence/{document_id}",
        retrieved_at=retrieved_at,
        chunk_count=2,
        status="indexed",
    )


def _claim(
    claim_id: str,
    *,
    source_id: str,
    metric: str,
    value: str,
    state: str = "candidate",
    publication_date: date | None = None,
    evidence: str = "Official source evidence",
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{source_id}",
        source_id=source_id,
        source_url=f"https://example.test/{claim_id}",
        entity=source_id.upper(),
        metric=metric,
        value_text=value,
        value_numeric=Decimal("1.0"),
        unit="%",
        publication_date=publication_date,
        effective_date=None,
        evidence_text=evidence,
        evidence_chunk_index=0,
        confidence=0.9,
        state=state,
        created_at=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
    )


def test_snapshot_filters_known_quality_noise_without_mutating_history(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _document("doc-rbi", "rbi", datetime(2026, 9, 16, 9, 0, tzinfo=UTC)),
                _document("doc-sebi", "sebi", datetime(2026, 9, 15, 9, 0, tzinfo=UTC)),
                _claim(
                    "claim-good",
                    source_id="rbi",
                    metric="Policy Repo Rate",
                    value="5.50%",
                    publication_date=date(2026, 9, 16),
                ),
                _claim(
                    "claim-noise",
                    source_id="rbi",
                    metric="Posted On",
                    value="16",
                    publication_date=date(2026, 9, 16),
                ),
                _claim(
                    "claim-conflict",
                    source_id="sebi",
                    metric="Example Metric",
                    value="2%",
                    state="conflicted",
                    publication_date=date(2026, 9, 15),
                ),
                _claim(
                    "claim-old",
                    source_id="sebi",
                    metric="Old Metric",
                    value="1%",
                    state="superseded",
                    publication_date=date(2026, 8, 1),
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(intelligence, "get_session", lambda: Session())

    result = intelligence.build_intelligence_snapshot(limit=10)

    assert result["summary"]["documents"] == 2
    assert result["summary"]["claims"] == 4
    assert result["summary"]["quality_filtered_claims"] == 1
    assert result["summary"]["active_quality_safe_claims"] == 2
    assert result["summary"]["conflicted_claims"] == 1
    assert [row["claim_id"] for row in result["latest_active_claims"]] == [
        "claim-good",
        "claim-conflict",
    ]
    assert result["conflicts"][0]["claim_id"] == "claim-conflict"
    assert result["interpretation"]["conflict_attention_required"] is True

    with Session() as session:
        states = {row.id: row.state for row in session.scalars(select(ClaimRecord))}
    assert states["claim-noise"] == "candidate"
    assert states["claim-old"] == "superseded"


def test_snapshot_can_scope_to_one_source(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _document("doc-rbi", "rbi", datetime(2026, 9, 16, 9, 0, tzinfo=UTC)),
                _document("doc-sebi", "sebi", datetime(2026, 9, 15, 9, 0, tzinfo=UTC)),
                _claim("claim-rbi", source_id="rbi", metric="CRR", value="4%"),
                _claim("claim-sebi", source_id="sebi", metric="Example Metric", value="2%"),
            ]
        )
        session.commit()

    monkeypatch.setattr(intelligence, "get_session", lambda: Session())
    result = intelligence.build_intelligence_snapshot(source_id="rbi")

    assert result["summary"]["documents"] == 1
    assert result["summary"]["claims"] == 1
    assert result["source_coverage"] == [{"source_id": "rbi", "documents": 1, "claims": 1}]


def test_protected_intelligence_endpoint_reuses_dashboard_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type("Settings", (), {"dashboard_username": "operator", "dashboard_password": "secret"})(),
    )
    monkeypatch.setattr(
        dashboard_api,
        "build_intelligence_snapshot",
        lambda **kwargs: {
            "scope": kwargs,
            "summary": {"documents": 19, "claims": 40},
            "interpretation": {"safety_note": "read-only"},
        },
    )

    unauthenticated = client.get("/dashboard/intelligence")
    authenticated = client.get(
        "/dashboard/intelligence?source_id=rbi&limit=5",
        auth=("operator", "secret"),
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.headers["cache-control"] == "no-store"
    assert authenticated.json()["scope"] == {"source_id": "rbi", "limit": 5}
