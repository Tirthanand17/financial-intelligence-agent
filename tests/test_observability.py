from __future__ import annotations

import json

from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.observability as observability
from app.main import app


client = TestClient(app)


def test_request_observability_adds_server_id_and_omits_sensitive_inputs(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(observability.logger, "info", lambda message: messages.append(message))

    response = client.get(
        "/health?secret_query=do-not-log",
        headers={
            "Authorization": "Bearer should-not-log",
            "Cookie": "session=should-not-log",
            "X-Request-ID": "caller-controlled-id-must-not-be-trusted",
        },
    )

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    int(request_id, 16)
    assert request_id != "caller-controlled-id-must-not-be-trusted"

    assert len(messages) == 1
    event = json.loads(messages[0])
    assert event["event"] == "http_request"
    assert event["request_id"] == request_id
    assert event["method"] == "GET"
    assert event["path"] == "/health"
    assert event["status_code"] == 200
    assert event["outcome"] == "completed"
    assert isinstance(event["duration_ms"], float)

    serialized = messages[0].casefold()
    assert "secret_query" not in serialized
    assert "do-not-log" not in serialized
    assert "authorization" not in serialized
    assert "should-not-log" not in serialized
    assert "cookie" not in serialized
    assert "caller-controlled-id" not in serialized


def test_protected_auth_failure_is_correlated_without_logging_credentials(monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(observability.logger, "info", lambda message: messages.append(message))
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )

    response = client.get("/dashboard", auth=("wrong-user", "wrong-password"))

    assert response.status_code == 401
    assert response.headers["x-request-id"]
    event = json.loads(messages[-1])
    assert event["status_code"] == 401
    assert event["path"] == "/dashboard"
    serialized = messages[-1].casefold()
    assert "wrong-user" not in serialized
    assert "wrong-password" not in serialized
    assert "operator" not in serialized
    assert "secret" not in serialized


def test_log_record_contains_only_bounded_runtime_metadata(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret-db")
    monkeypatch.setenv("QDRANT_API_KEY", "secret-vector-key")

    record = observability.build_request_log_record(
        request_id="abc",
        method="GET",
        path="/api/v1/intelligence",
        status_code=200,
        duration_ms=12.34567,
        outcome="completed",
    )

    assert record["git_commit"] == "abc123"
    assert record["github_run_id"] == "12345"
    assert record["duration_ms"] == 12.346
    serialized = json.dumps(record).casefold()
    assert "database_url" not in serialized
    assert "secret-db" not in serialized
    assert "qdrant_api_key" not in serialized
    assert "secret-vector-key" not in serialized


def test_request_context_is_reset_after_response(monkeypatch) -> None:
    monkeypatch.setattr(observability.logger, "info", lambda _message: None)
    assert observability.current_request_id() is None
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert observability.current_request_id() is None
