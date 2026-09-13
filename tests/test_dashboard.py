from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
from app.main import app


client = TestClient(app)


def _settings(username: str | None, password: str | None):
    return SimpleNamespace(dashboard_username=username, dashboard_password=password)


def test_dashboard_fails_closed_when_credentials_are_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_api, "get_settings", lambda: _settings(None, None))

    response = client.get("/dashboard")

    assert response.status_code == 503
    assert response.json()["detail"] == "Dashboard authentication is not configured."


def test_dashboard_requires_valid_basic_auth(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_api, "get_settings", lambda: _settings("operator", "secret"))

    unauthenticated = client.get("/dashboard")
    invalid = client.get("/dashboard", auth=("operator", "wrong"))
    valid = client.get("/dashboard", auth=("operator", "secret"))

    assert unauthenticated.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert "Private read-only operational dashboard" in valid.text


def test_dashboard_status_is_secret_free_read_only_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(dashboard_api, "get_settings", lambda: _settings("operator", "secret"))
    monkeypatch.setattr(
        dashboard_api,
        "build_dashboard_snapshot",
        lambda: {
            "overall_status": "healthy",
            "totals": {"documents": 15, "claims": 40, "trust_events": 0},
            "monitors": [],
            "recent_runs": [],
        },
    )

    response = client.get("/dashboard/status", auth=("operator", "secret"))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["overall_status"] == "healthy"
    assert "secret" not in response.text.lower()


def test_dashboard_has_no_write_controls() -> None:
    text = dashboard_api.DASHBOARD_HTML.lower()

    assert "--allow-write" not in text
    assert "/ingest" not in text
    assert "trust_promotion_enabled=true" not in text
