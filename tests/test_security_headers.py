from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
from app.main import app
from app.security_headers import DASHBOARD_CONTENT_SECURITY_POLICY


client = TestClient(app)


def _enable_dashboard_auth(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )


def test_dashboard_html_receives_browser_security_headers(monkeypatch) -> None:
    _enable_dashboard_auth(monkeypatch)

    response = client.get("/dashboard", auth=("operator", "secret"))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["content-security-policy"] == DASHBOARD_CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")


def test_dashboard_json_and_auth_failures_are_not_cacheable(monkeypatch) -> None:
    _enable_dashboard_auth(monkeypatch)
    monkeypatch.setattr(
        dashboard_api,
        "build_dashboard_snapshot",
        lambda: {
            "overall_status": "healthy",
            "totals": {},
            "queue": {},
            "capacity": {},
            "monitors": [],
            "recent_runs": [],
        },
    )

    authenticated = client.get("/dashboard/status", auth=("operator", "secret"))
    unauthenticated = client.get("/dashboard")

    assert authenticated.status_code == 200
    assert authenticated.headers["cache-control"] == "no-store, max-age=0"
    assert authenticated.headers["content-security-policy"] == DASHBOARD_CONTENT_SECURITY_POLICY

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "no-store, max-age=0"
    assert unauthenticated.headers["pragma"] == "no-cache"
    assert unauthenticated.headers["x-frame-options"] == "DENY"


def test_non_dashboard_api_gets_baseline_headers_without_dashboard_csp() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" not in response.headers
    assert "pragma" not in response.headers
