from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.api.routes as routes_api
from app.main import app


client = TestClient(app)


def _settings(*, readonly_username=None, readonly_password=None):
    return type(
        "Settings",
        (),
        {
            "dashboard_username": "operator",
            "dashboard_password": "operator-secret",
            "dashboard_readonly_username": readonly_username,
            "dashboard_readonly_password": readonly_password,
        },
    )()


def test_optional_readonly_identity_can_access_get_evidence_surfaces(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: _settings(readonly_username="viewer", readonly_password="viewer-secret"),
    )

    dashboard = client.get("/dashboard", auth=("viewer", "viewer-secret"))
    api_meta = client.get("/api/v1", auth=("viewer", "viewer-secret"))
    hub = client.get("/dashboard/hub", auth=("viewer", "viewer-secret"))

    assert dashboard.status_code == 200
    assert api_meta.status_code == 200
    assert api_meta.json()["safety"]["read_only"] is True
    assert hub.status_code == 200


def test_optional_readonly_identity_cannot_reach_operator_post_services(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: _settings(readonly_username="viewer", readonly_password="viewer-secret"),
    )
    calls = {"ingest": 0, "ask": 0}

    def fake_ingest(*args, **kwargs):
        calls["ingest"] += 1
        raise AssertionError("read-only identity reached ingestion service")

    def fake_ask(*args, **kwargs):
        calls["ask"] += 1
        raise AssertionError("read-only identity reached retrieval service")

    monkeypatch.setattr(routes_api, "ingest_url", fake_ingest)
    monkeypatch.setattr(routes_api, "answer_question", fake_ask)

    ingest = client.post(
        "/ingest",
        auth=("viewer", "viewer-secret"),
        json={"source_id": "rbi", "url": "https://www.rbi.org.in/"},
    )
    ask = client.post(
        "/ask",
        auth=("viewer", "viewer-secret"),
        json={"question": "What is the policy repo rate?"},
    )

    assert ingest.status_code == 401
    assert ask.status_code == 401
    assert calls == {"ingest": 0, "ask": 0}


def test_operator_keeps_full_existing_access_when_readonly_role_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: _settings(readonly_username="viewer", readonly_password="viewer-secret"),
    )
    monkeypatch.setattr(
        routes_api,
        "ingest_url",
        lambda source_id, url: {"status": "indexed", "source_id": source_id, "source_url": url},
    )
    monkeypatch.setattr(
        routes_api,
        "answer_question",
        lambda question, *, top_k, source_id: {
            "answer": "grounded",
            "question": question,
            "top_k": top_k,
            "source_id": source_id,
        },
    )

    assert client.get("/dashboard", auth=("operator", "operator-secret")).status_code == 200
    ingest = client.post(
        "/ingest",
        auth=("operator", "operator-secret"),
        json={"source_id": "rbi", "url": "https://www.rbi.org.in/"},
    )
    ask = client.post(
        "/ask",
        auth=("operator", "operator-secret"),
        json={"question": "What is the policy repo rate?", "top_k": 3},
    )

    assert ingest.status_code == 200
    assert ask.status_code == 200


def test_unset_readonly_role_preserves_single_operator_behavior(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_api, "get_settings", lambda: _settings())

    assert client.get("/dashboard", auth=("operator", "operator-secret")).status_code == 200
    assert client.get("/dashboard", auth=("viewer", "viewer-secret")).status_code == 401


def test_partial_readonly_configuration_fails_closed_for_read_surfaces(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: _settings(readonly_username="viewer", readonly_password=None),
    )

    response = client.get("/dashboard", auth=("operator", "operator-secret"))

    assert response.status_code == 503
    assert "incompletely configured" in response.json()["detail"].lower()
