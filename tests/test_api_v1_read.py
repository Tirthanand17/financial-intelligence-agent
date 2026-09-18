from datetime import date

from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.api.v1_read as api_v1
from app.main import app


client = TestClient(app)


def _enable_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )


def test_api_v1_meta_is_private_read_only_and_non_cacheable(monkeypatch) -> None:
    _enable_auth(monkeypatch)

    unauthenticated = client.get("/api/v1")
    authenticated = client.get("/api/v1", auth=("operator", "secret"))

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "no-store"
    assert "basic" in unauthenticated.headers["www-authenticate"].lower()

    assert authenticated.status_code == 200
    assert authenticated.headers["cache-control"] == "no-store"
    payload = authenticated.json()
    assert payload["api_version"] == "v1"
    assert payload["mode"] == "protected_read_only_evidence_api"
    assert payload["safety"]["read_only"] is True
    assert payload["safety"]["write_routes"] is False
    assert payload["safety"]["ingestion_controls"] is False
    assert payload["safety"]["trust_controls"] is False
    assert payload["safety"]["raw_object_keys_exposed"] is False


def test_api_v1_exposes_only_get_and_head_methods() -> None:
    versioned_routes = [route for route in app.routes if getattr(route, "path", "").startswith("/api/v1")]
    assert versioned_routes
    for route in versioned_routes:
        methods = set(getattr(route, "methods", set()))
        assert methods <= {"GET", "HEAD"}
        assert not ({"POST", "PUT", "PATCH", "DELETE"} & methods)


def test_api_v1_intelligence_forwards_bounded_scope(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    captured = {}

    def fake_snapshot(**kwargs):
        captured.update(kwargs)
        return {"scope": kwargs, "summary": {}}

    monkeypatch.setattr(api_v1, "build_intelligence_snapshot", fake_snapshot)
    response = client.get(
        "/api/v1/intelligence?source_id=rbi&limit=7",
        auth=("operator", "secret"),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert captured == {"source_id": "rbi", "limit": 7}


def test_api_v1_search_forwards_filters_and_rejects_bad_date_range(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        if kwargs["date_from"] and kwargs["date_to"] and kwargs["date_from"] > kwargs["date_to"]:
            raise ValueError("date_from must be on or before date_to")
        return {"scope": kwargs, "claims": [], "documents": []}

    monkeypatch.setattr(api_v1, "build_evidence_search_snapshot", fake_search)
    response = client.get(
        "/api/v1/evidence/search?q=repo&source_id=rbi&state=candidate&entity=Reserve&metric=Repo&date_from=2026-09-01&date_to=2026-09-18&limit=20&offset=5",
        auth=("operator", "secret"),
    )

    assert response.status_code == 200
    assert captured["q"] == "repo"
    assert captured["source_id"] == "rbi"
    assert captured["state"] == "candidate"
    assert captured["entity"] == "Reserve"
    assert captured["metric"] == "Repo"
    assert captured["date_from"] == date(2026, 9, 1)
    assert captured["date_to"] == date(2026, 9, 18)
    assert captured["limit"] == 20
    assert captured["offset"] == 5

    invalid = client.get(
        "/api/v1/evidence/search?date_from=2026-09-18&date_to=2026-09-01",
        auth=("operator", "secret"),
    )
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert "date_from must be on or before date_to" in invalid.json()["detail"]


def test_api_v1_document_and_provenance_fail_closed_on_missing(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    monkeypatch.setattr(api_v1, "build_document_detail", lambda _document_id: None)
    monkeypatch.setattr(api_v1, "build_provenance_graph", lambda _document_id: None)

    document = client.get("/api/v1/documents/missing", auth=("operator", "secret"))
    provenance = client.get("/api/v1/provenance/missing", auth=("operator", "secret"))

    assert document.status_code == 404
    assert provenance.status_code == 404
    assert document.headers["cache-control"] == "no-store"
    assert provenance.headers["cache-control"] == "no-store"


def test_api_v1_timeline_conflicts_and_scorecards_are_read_only_wrappers(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    timeline_calls = {}
    conflict_calls = {}

    monkeypatch.setattr(
        api_v1,
        "build_timeline_snapshot",
        lambda **kwargs: timeline_calls.update(kwargs) or {"scope": kwargs, "series": []},
    )
    monkeypatch.setattr(
        api_v1,
        "build_conflict_investigation_snapshot",
        lambda **kwargs: conflict_calls.update(kwargs) or {"scope": kwargs, "conflicts": []},
    )
    monkeypatch.setattr(
        api_v1,
        "build_evidence_quality_scorecards",
        lambda: {
            "mode": "read_only_factual_evidence_quality_scorecards",
            "interpretation": {"composite_score": None, "ranking": False},
        },
    )

    timeline = client.get(
        "/api/v1/timeline?entity=Reserve%20Bank&metric=Repo%20Rate&source_id=rbi&series_limit=10&points_per_series=15",
        auth=("operator", "secret"),
    )
    conflicts = client.get(
        "/api/v1/conflicts?participant_source_id=rbi&entity_contains=Reserve&metric_contains=Repo&limit=20",
        auth=("operator", "secret"),
    )
    scorecards = client.get("/api/v1/quality/scorecards", auth=("operator", "secret"))

    assert timeline.status_code == 200
    assert timeline_calls == {
        "entity": "Reserve Bank",
        "metric": "Repo Rate",
        "source_id": "rbi",
        "series_limit": 10,
        "points_per_series": 15,
    }
    assert conflicts.status_code == 200
    assert conflict_calls == {
        "participant_source_id": "rbi",
        "entity_contains": "Reserve",
        "metric_contains": "Repo",
        "limit": 20,
    }
    assert scorecards.status_code == 200
    assert scorecards.json()["interpretation"]["composite_score"] is None


def test_api_v1_query_bounds_are_enforced_before_services(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    assert client.get("/api/v1/intelligence?limit=51", auth=("operator", "secret")).status_code == 422
    assert client.get("/api/v1/evidence/search?limit=101", auth=("operator", "secret")).status_code == 422
    assert client.get("/api/v1/evidence/search?offset=5001", auth=("operator", "secret")).status_code == 422
    assert client.get("/api/v1/timeline?series_limit=51", auth=("operator", "secret")).status_code == 422
    assert client.get("/api/v1/conflicts?limit=101", auth=("operator", "secret")).status_code == 422
