from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.api.routes as routes_api
from app.main import app


client = TestClient(app)


def _enable_operator_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )


def test_legacy_private_post_endpoints_fail_closed_before_service_call(monkeypatch) -> None:
    _enable_operator_auth(monkeypatch)
    calls = {"ingest": 0, "ask": 0}

    def fake_ingest(*args, **kwargs):
        calls["ingest"] += 1
        raise AssertionError("unauthenticated request reached ingestion service")

    def fake_ask(*args, **kwargs):
        calls["ask"] += 1
        raise AssertionError("unauthenticated request reached retrieval service")

    monkeypatch.setattr(routes_api, "ingest_url", fake_ingest)
    monkeypatch.setattr(routes_api, "answer_question", fake_ask)

    ingest = client.post(
        "/ingest",
        json={"source_id": "rbi", "url": "https://www.rbi.org.in/"},
    )
    ask = client.post(
        "/ask",
        json={"question": "What is the policy repo rate?", "top_k": 5},
    )

    assert ingest.status_code == 401
    assert ask.status_code == 401
    assert ingest.headers["www-authenticate"] == "Basic"
    assert ask.headers["www-authenticate"] == "Basic"
    assert calls == {"ingest": 0, "ask": 0}


def test_legacy_private_post_endpoints_reject_invalid_operator_credentials(monkeypatch) -> None:
    _enable_operator_auth(monkeypatch)

    ingest = client.post(
        "/ingest",
        auth=("operator", "wrong"),
        json={"source_id": "rbi", "url": "https://www.rbi.org.in/"},
    )
    ask = client.post(
        "/ask",
        auth=("wrong", "secret"),
        json={"question": "What is the policy repo rate?"},
    )

    assert ingest.status_code == 401
    assert ask.status_code == 401


def test_legacy_private_post_endpoints_allow_valid_operator_and_preserve_contract(monkeypatch) -> None:
    _enable_operator_auth(monkeypatch)

    monkeypatch.setattr(
        routes_api,
        "ingest_url",
        lambda source_id, url: {
            "status": "indexed",
            "source_id": source_id,
            "source_url": url,
        },
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

    ingest = client.post(
        "/ingest",
        auth=("operator", "secret"),
        json={"source_id": "rbi", "url": "https://www.rbi.org.in/"},
    )
    ask = client.post(
        "/ask",
        auth=("operator", "secret"),
        json={"question": "What is the policy repo rate?", "top_k": 3, "source_id": "rbi"},
    )

    assert ingest.status_code == 200
    assert ingest.json()["status"] == "indexed"
    assert ingest.json()["source_id"] == "rbi"

    assert ask.status_code == 200
    assert ask.json()["answer"] == "grounded"
    assert ask.json()["top_k"] == 3
    assert ask.json()["source_id"] == "rbi"


def test_private_endpoints_fail_closed_when_operator_auth_is_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": None, "dashboard_password": None},
        )(),
    )

    response = client.post(
        "/ingest",
        json={"source_id": "rbi", "url": "https://www.rbi.org.in/"},
    )

    assert response.status_code == 503


def test_source_registry_route_remains_read_only_and_non_secret() -> None:
    response = client.get("/sources")

    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert {"source_id", "name", "category", "authority_level", "base_url", "enabled"} <= set(
        payload[0]
    )
    serialized = response.text.lower()
    assert "api_key" not in serialized
    assert "password" not in serialized
    assert "database_url" not in serialized
