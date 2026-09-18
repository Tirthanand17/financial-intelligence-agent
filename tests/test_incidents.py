from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.api.incidents_dashboard as incidents_api
import app.services.incidents as incidents_service
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


def _readiness(*, unsafe: bool = False) -> dict[str, object]:
    return {
        "generated_at": "2026-09-18T03:30:00+00:00",
        "overall_status": "blocked" if unsafe else "healthy",
        "checks": {
            "capacity_safe": not unsafe,
            "qdrant_points_match": not unsafe,
            "unexpected_trust_events_absent": not unsafe,
            "all_monitors_ready": not unsafe,
            "runtime_gates_at_safe_defaults": not unsafe,
            "queue_has_no_failed_items": not unsafe,
            "recent_monitor_runs_have_no_failures": not unsafe,
            "cloud_measurements_available": not unsafe,
        },
        "blocking_or_attention_checks": [] if not unsafe else ["capacity_safe"],
        "cloud_checks": {
            "supabase_measurement_available": not unsafe,
            "backblaze_b2_measurement_available": True,
            "qdrant_measurement_available": True,
            "qdrant_points_match": not unsafe,
        },
        "gate_drift": {} if not unsafe else {"trust_promotion_enabled": True},
        "totals": {
            "trust_events": 0 if not unsafe else 1,
            "expected_qdrant_points": 53,
            "actual_qdrant_points": 53 if not unsafe else 52,
        },
        "queue": {"failed": 0 if not unsafe else 2},
        "capacity": {"safe": not unsafe, "usage": {}},
        "monitors": [
            {
                "source_id": "rbi",
                "state": "ready" if not unsafe else "blocked",
                "consecutive_failures": 0 if not unsafe else 2,
                "last_success_at": "2026-09-18T03:00:00+00:00",
                "last_error_code": None if not unsafe else "HTTP_FAILURE",
            }
        ],
        "recent_runs": [] if not unsafe else [
            {
                "source_id": "rbi",
                "outcome": "failed",
                "started_at": "2026-09-18T03:00:00+00:00",
                "finished_at": "2026-09-18T03:01:00+00:00",
                "error_code": "HTTP_FAILURE",
            }
        ],
    }


def test_incident_evaluator_is_clear_when_readiness_is_safe(monkeypatch) -> None:
    monkeypatch.setattr(incidents_service, "build_readiness_snapshot", lambda: _readiness())
    snapshot = incidents_service.build_incident_snapshot()

    assert snapshot["status"] == "clear"
    assert snapshot["summary"]["incidents"] == 0
    assert snapshot["summary"]["notification_delivery_configured"] is False
    assert snapshot["incidents"] == []
    assert snapshot["safety"]["read_only"] is True
    assert snapshot["safety"]["sends_external_notifications"] is False


def test_incident_evaluator_surfaces_fail_closed_conditions(monkeypatch) -> None:
    monkeypatch.setattr(incidents_service, "build_readiness_snapshot", lambda: _readiness(unsafe=True))
    snapshot = incidents_service.build_incident_snapshot()

    assert snapshot["status"] == "blocked"
    codes = {item["code"] for item in snapshot["incidents"]}
    assert {
        "CAPACITY_UNSAFE",
        "QDRANT_POINT_MISMATCH",
        "UNEXPECTED_TRUST_EVENTS",
        "RUNTIME_GATE_DRIFT",
        "CLOUD_MEASUREMENT_UNAVAILABLE",
        "QUEUE_FAILED_ITEMS",
        "SOURCE_MONITOR_NOT_READY",
        "RECENT_MONITOR_RUN_FAILED",
    } <= codes
    assert snapshot["summary"]["critical"] >= 4
    assert snapshot["summary"]["high"] >= 4


def test_incident_routes_are_private_read_only_and_non_cacheable(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    payload = {
        "generated_at": "2026-09-18T03:30:00+00:00",
        "mode": "read_only_incident_evaluator",
        "status": "clear",
        "summary": {"incidents": 0, "critical": 0, "high": 0, "medium": 0, "notification_delivery_configured": False},
        "incidents": [],
        "readiness_status": "healthy",
        "blocking_or_attention_checks": [],
        "safety": {"note": "read-only", "read_only": True},
    }
    monkeypatch.setattr(incidents_api, "build_incident_snapshot", lambda: payload)

    assert client.get("/dashboard/incidents").status_code == 401
    page = client.get("/dashboard/incidents", auth=("operator", "secret"))
    status = client.get("/dashboard/incidents/status", auth=("operator", "secret"))
    api = client.get("/api/v1/incidents", auth=("operator", "secret"))

    assert page.status_code == 200
    assert "Incident Center" in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert "/ingest" not in page.text
    assert status.status_code == 200
    assert api.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert api.headers["cache-control"] == "no-store"
    assert api.json()["summary"]["notification_delivery_configured"] is False


def test_incident_api_openapi_contract_has_no_write_methods() -> None:
    operations = app.openapi()["paths"]["/api/v1/incidents"]
    methods = {method.lower() for method in operations}
    assert not ({"post", "put", "patch", "delete"} & methods)
    assert methods <= {"get", "head", "options"}
