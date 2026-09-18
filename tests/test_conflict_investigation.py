from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.conflict_investigation_dashboard as conflict_api
import app.api.dashboard as dashboard_api
import app.services.conflict_investigation as conflict_service
from app.main import app
from app.storage.database import Base, ClaimRecord, DocumentRecord


client = TestClient(app)


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _document(document_id: str, source_id: str) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        source_id=source_id,
        source_name=source_id.upper(),
        source_url=f"https://example.test/{document_id}",
        final_url=f"https://example.test/{document_id}.pdf",
        title=f"Evidence {document_id}",
        content_type="application/pdf",
        sha256=(document_id * 64)[:64],
        object_key=f"private/{document_id}.pdf",
        retrieved_at=datetime(2026, 9, 18, 1, 0, tzinfo=UTC),
        chunk_count=1,
        status="indexed",
    )


def _claim(
    claim_id: str,
    document_id: str,
    source_id: str,
    *,
    metric: str,
    value: str,
    numeric: str,
    publication_date: date | None = date(2026, 9, 1),
    state: str = "candidate",
    evidence: str | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=document_id,
        source_id=source_id,
        source_url=f"https://example.test/{document_id}",
        entity="India Monetary Authority",
        metric=metric,
        value_text=value,
        value_numeric=Decimal(numeric),
        unit="%",
        publication_date=publication_date,
        effective_date=None,
        evidence_text=evidence or f"The {metric} is {value}.",
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
        created_at=datetime(2026, 9, 18, 1, 5, tzinfo=UTC),
        updated_at=datetime(2026, 9, 18, 1, 5, tzinfo=UTC),
    )


def test_independent_exact_alias_values_are_surfaced_without_resolution(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all([
            _document("doc-rbi", "rbi"),
            _document("doc-imf", "imf"),
            _claim("rbi-claim", "doc-rbi", "rbi", metric="Repo Rate", value="5.50%", numeric="5.50"),
            _claim("imf-claim", "doc-imf", "imf", metric="Policy Repo Rate", value="5.75%", numeric="5.75"),
        ])
        session.commit()

    monkeypatch.setattr(conflict_service, "get_session", lambda: Session())
    result = conflict_service.build_conflict_investigation_snapshot()

    assert result["summary"]["independent_conflict_groups"] == 1
    conflict = result["conflicts"][0]
    assert conflict["indicator_id"] == "policy_repo_rate"
    assert conflict["canonical_metric"] == "Policy Repo Rate"
    assert conflict["distinct_values"] == 2
    assert set(conflict["independence_groups"]) == {"rbi", "imf"}
    assert {group["display_value"] for group in conflict["values"]} == {"5.50%", "5.75%"}
    assert result["safety"]["resolves_conflicts_automatically"] is False
    assert result["safety"]["mutates_claim_state"] is False

    with Session() as session:
        states = list(session.scalars(select(ClaimRecord.state)))
        assert states == ["candidate", "candidate"]


def test_same_value_independent_claims_are_counted_as_agreement_not_conflict(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all([
            _document("doc-rbi-agree", "rbi"),
            _document("doc-imf-agree", "imf"),
            _claim("agree-rbi", "doc-rbi-agree", "rbi", metric="Repo Rate", value="5.50%", numeric="5.50"),
            _claim("agree-imf", "doc-imf-agree", "imf", metric="Policy Repo Rate", value="5.50%", numeric="5.50"),
        ])
        session.commit()

    monkeypatch.setattr(conflict_service, "get_session", lambda: Session())
    result = conflict_service.build_conflict_investigation_snapshot()

    assert result["summary"]["independent_conflict_groups"] == 0
    assert result["summary"]["independent_agreement_groups"] == 1
    assert result["conflicts"] == []


def test_undated_and_quality_failed_claims_do_not_create_false_conflicts(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all([
            _document("doc-undated", "rbi"),
            _document("doc-quality", "imf"),
            _claim(
                "undated",
                "doc-undated",
                "rbi",
                metric="Repo Rate",
                value="5.50%",
                numeric="5.50",
                publication_date=None,
            ),
            _claim(
                "quality",
                "doc-quality",
                "imf",
                metric="Page Number",
                value="5.75%",
                numeric="5.75",
                evidence="Page Number: 5.75",
            ),
        ])
        session.commit()

    monkeypatch.setattr(conflict_service, "get_session", lambda: Session())
    result = conflict_service.build_conflict_investigation_snapshot()

    assert result["summary"]["independent_conflict_groups"] == 0
    assert result["summary"]["missing_temporal_scope_excluded"] == 1
    assert result["summary"]["quality_failed_excluded"] == 1
    assert result["safety"]["invented_dates"] is False


def test_participant_source_filter_keeps_other_conflict_members(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all([
            _document("doc-rbi-filter", "rbi"),
            _document("doc-imf-filter", "imf"),
            _claim("filter-rbi", "doc-rbi-filter", "rbi", metric="Repo Rate", value="5.50%", numeric="5.50"),
            _claim("filter-imf", "doc-imf-filter", "imf", metric="Policy Repo Rate", value="5.75%", numeric="5.75"),
        ])
        session.commit()

    monkeypatch.setattr(conflict_service, "get_session", lambda: Session())
    result = conflict_service.build_conflict_investigation_snapshot(participant_source_id="rbi")

    assert result["summary"]["independent_conflict_groups"] == 1
    assert set(result["conflicts"][0]["source_ids"]) == {"rbi", "imf"}


def test_conflict_routes_are_private_and_read_only(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type("Settings", (), {"dashboard_username": "operator", "dashboard_password": "secret"})(),
    )
    monkeypatch.setattr(
        conflict_api,
        "build_conflict_investigation_snapshot",
        lambda **kwargs: {
            "generated_at": "2026-09-18T02:00:00+00:00",
            "scope": kwargs,
            "summary": {
                "active_claims_scanned": 2,
                "comparison_groups_in_scope": 1,
                "independent_conflict_groups": 1,
                "independent_agreement_groups": 0,
                "single_independence_group_groups": 0,
                "quality_failed_excluded": 0,
                "missing_temporal_scope_excluded": 0,
                "returned_conflict_groups": 1,
            },
            "conflicts": [],
            "comparison_contract": {
                "entity": "exact_normalized",
                "metric": "exact_catalog_alias_else_exact_normalized_source_metric",
                "unit": "exact_normalized",
                "temporal_scope": "persisted",
                "publisher_independence": True,
            },
            "safety": {"note": "read-only"},
        },
    )

    assert client.get("/dashboard/conflicts").status_code == 401
    page = client.get("/dashboard/conflicts", auth=("operator", "secret"))
    status_response = client.get(
        "/dashboard/conflicts/status?participant_source_id=rbi&limit=20",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Conflict Investigation" in page.text
    lowered = page.text.lower()
    assert "/ingest" not in lowered
    assert "method=\"post\"" not in lowered
    assert "trust_promotion_enabled=true" not in lowered
    assert status_response.status_code == 200
    assert status_response.headers["cache-control"] == "no-store"
    assert status_response.json()["scope"]["participant_source_id"] == "rbi"
