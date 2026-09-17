from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.change_detection_dashboard as change_api
import app.api.dashboard as dashboard_api
import app.services.change_detection as changes
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
    value_text: str,
    numeric: str | None,
    publication_date: date | None,
    state: str = "candidate",
    metric: str = "Policy Repo Rate",
    source_id: str = "rbi",
    unit: str | None = "%",
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        fingerprint=(claim_id * 64)[:64],
        document_id=f"doc-{claim_id}",
        source_id=source_id,
        source_url=f"https://example.test/{claim_id}",
        entity="Reserve Bank of India",
        metric=metric,
        value_text=value_text,
        value_numeric=Decimal(numeric) if numeric is not None else None,
        unit=unit,
        publication_date=publication_date,
        effective_date=None,
        evidence_text=f"{metric}: {value_text}",
        evidence_chunk_index=0,
        confidence=0.95,
        state=state,
        created_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 17, 5, 0, tzinfo=UTC),
    )


def test_detects_numeric_change_and_counts_unchanged_without_mutation(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim("one", value_text="6.00%", numeric="6.00", publication_date=date(2026, 1, 1)),
                _claim("two", value_text="5.50%", numeric="5.50", publication_date=date(2026, 2, 1)),
                _claim("three", value_text="5.50%", numeric="5.50", publication_date=date(2026, 3, 1)),
            ]
        )
        session.commit()

    monkeypatch.setattr(changes, "get_session", lambda: Session())
    result = changes.build_change_detection_snapshot()

    assert result["summary"]["eligible_dated_claims"] == 3
    assert result["summary"]["detected_changes"] == 1
    assert result["summary"]["unchanged_confirmations"] == 1
    event = result["changes"][0]
    assert event["change_kind"] == "numeric_value_change"
    assert Decimal(event["numeric_delta"]) == Decimal("-0.50")
    assert event["direction"] == "decrease"
    assert event["previous"]["claim_id"] == "one"
    assert event["current"]["claim_id"] == "two"
    assert result["safety"]["mutates_data"] is False
    assert result["safety"]["invented_dates"] is False

    with Session() as session:
        assert {row.id: row.state for row in session.scalars(select(ClaimRecord))} == {
            "one": "candidate",
            "two": "candidate",
            "three": "candidate",
        }


def test_keeps_superseded_claim_for_explicit_history(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim(
                    "old",
                    value_text="5.50%",
                    numeric="5.50",
                    publication_date=date(2026, 4, 1),
                    state="superseded",
                ),
                _claim(
                    "new",
                    value_text="5.50%",
                    numeric="5.50",
                    publication_date=date(2026, 5, 1),
                    state="candidate",
                ),
                ClaimSupersessionRecord(
                    older_claim_id="old",
                    newer_claim_id="new",
                    newer_document_id="doc-new",
                    temporal_kind="publication",
                    older_date=date(2026, 4, 1),
                    newer_date=date(2026, 5, 1),
                    created_at=datetime(2026, 5, 1, 6, 0, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(changes, "get_session", lambda: Session())
    result = changes.build_change_detection_snapshot()

    assert result["summary"]["eligible_dated_claims"] == 2
    assert result["summary"]["detected_changes"] == 1
    event = result["changes"][0]
    assert event["change_kind"] == "supersession_same_value"
    assert event["explicit_supersession"] is True
    assert event["previous"]["state"] == "superseded"


def test_excludes_undated_quality_failed_and_rejected_claims(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim("good", value_text="5.50%", numeric="5.50", publication_date=date(2026, 6, 1)),
                _claim("undated", value_text="5.25%", numeric="5.25", publication_date=None),
                _claim(
                    "metadata",
                    value_text="17",
                    numeric="17",
                    publication_date=date(2026, 6, 2),
                    metric="Date",
                    unit=None,
                ),
                _claim(
                    "rejected",
                    value_text="5.00%",
                    numeric="5.00",
                    publication_date=date(2026, 6, 3),
                    state="rejected",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(changes, "get_session", lambda: Session())
    result = changes.build_change_detection_snapshot()

    assert result["summary"]["eligible_dated_claims"] == 1
    assert result["excluded_reason_counts"]["missing_temporal_scope"] == 1
    assert result["excluded_reason_counts"]["quality:metadata_metric"] == 1
    assert result["excluded_reason_counts"]["rejected_state"] == 1


def test_source_filter_preserves_exact_source_identity(monkeypatch) -> None:
    Session = _session_factory()
    with Session() as session:
        session.add_all(
            [
                _claim("rbi-a", value_text="6.00%", numeric="6.00", publication_date=date(2026, 1, 1)),
                _claim("rbi-b", value_text="5.50%", numeric="5.50", publication_date=date(2026, 2, 1)),
                _claim(
                    "other",
                    value_text="5.25%",
                    numeric="5.25",
                    publication_date=date(2026, 3, 1),
                    source_id="sebi",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr(changes, "get_session", lambda: Session())
    result = changes.build_change_detection_snapshot(source_id="rbi")

    assert result["summary"]["eligible_dated_claims"] == 2
    assert all(
        observation["source_id"] == "rbi"
        for event in result["changes"]
        for observation in (event["previous"], event["current"])
    )


def test_change_detection_routes_are_private_and_read_only(monkeypatch) -> None:
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
        change_api,
        "build_change_detection_snapshot",
        lambda **kwargs: {
            "generated_at": "2026-09-17T12:00:00+00:00",
            "scope": kwargs,
            "summary": {
                "persisted_claims": 0,
                "eligible_dated_claims": 0,
                "series_compared": 0,
                "detected_changes": 0,
                "unchanged_confirmations": 0,
                "returned_changes": 0,
            },
            "change_kind_counts": {},
            "excluded_reason_counts": {},
            "changes": [],
            "safety": {"note": "read-only"},
        },
    )

    assert client.get("/dashboard/changes").status_code == 401
    page = client.get("/dashboard/changes", auth=("operator", "secret"))
    status = client.get(
        "/dashboard/changes/status?source_id=rbi&limit=25",
        auth=("operator", "secret"),
    )

    assert page.status_code == 200
    assert "Evidence Change Detection" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["scope"] == {"source_id": "rbi", "entity": None, "limit": 25}
