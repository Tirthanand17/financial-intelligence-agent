from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
from app.main import app


client = TestClient(app)


def test_dashboard_hub_reuses_auth_and_exposes_only_read_only_navigation(monkeypatch) -> None:
    monkeypatch.setattr(
        dashboard_api,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"dashboard_username": "operator", "dashboard_password": "secret"},
        )(),
    )

    assert client.get("/dashboard/hub").status_code == 401
    response = client.get("/dashboard/hub", auth=("operator", "secret"))

    assert response.status_code == 200
    assert "Financial Intelligence Workspace" in response.text
    for route in (
        "/dashboard",
        "/dashboard/readiness",
        "/dashboard/intelligence-view",
        "/dashboard/search",
        "/dashboard/verification",
        "/dashboard/quality-coverage",
        "/dashboard/indicator-catalog",
        "/dashboard/timeline",
        "/dashboard/changes",
    ):
        assert route in response.text

    lowered = response.text.lower()
    assert "/ingest" not in lowered
    assert "method=\"post\"" not in lowered
    assert "trust_promotion_enabled=true" not in lowered
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
