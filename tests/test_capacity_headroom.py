from fastapi.testclient import TestClient

import app.api.capacity_headroom_dashboard as capacity_api
import app.api.dashboard as dashboard_api
import app.services.capacity_headroom as capacity
from app.main import app


client = TestClient(app)
_MIB = 1024 * 1024


def _settings():
    return type(
        "Settings",
        (),
        {
            "monitor_supabase_max_mb": 400,
            "monitor_b2_max_mb": 8192,
            "monitor_qdrant_max_points": 100000,
            "monitor_capacity_low_watermark_percent": 10,
        },
    )()


def _dashboard_snapshot(*, supabase=100 * _MIB, b2=1024 * _MIB, qdrant=10000, safe=True):
    return {
        "generated_at": "2026-09-18T04:00:00+00:00",
        "capacity": {
            "safe": safe,
            "reason": "all_required_cloud_capacity_ok" if safe else "cloud_capacity_unknown",
            "blocking_services": [] if safe else ["supabase"],
            "services": [
                {"service": "supabase", "state": "ok" if supabase is not None else "unknown", "detail": "test"},
                {"service": "backblaze_b2", "state": "ok" if b2 is not None else "unknown", "detail": "test"},
                {"service": "qdrant", "state": "ok" if qdrant is not None else "unknown", "detail": "test"},
            ],
            "usage": {
                "supabase_bytes": supabase,
                "backblaze_b2_bytes": b2,
                "qdrant_points": qdrant,
            },
        },
    }


def test_capacity_headroom_uses_only_measured_usage_and_project_ceilings(monkeypatch) -> None:
    monkeypatch.setattr(capacity, "get_settings", _settings)
    monkeypatch.setattr(capacity, "build_dashboard_snapshot", lambda: _dashboard_snapshot())

    result = capacity.build_capacity_headroom_snapshot()

    assert result["planning_status"] == "safe_headroom"
    by_service = {row["service"]: row for row in result["services"]}
    supabase = by_service["supabase"]
    assert supabase["used"] == 100 * _MIB
    assert supabase["ceiling"] == 400 * _MIB
    assert supabase["pause_threshold"] == 360 * _MIB
    assert supabase["remaining_to_pause_threshold"] == 260 * _MIB
    assert supabase["remaining_to_ceiling"] == 300 * _MIB
    assert supabase["usage_percent"] == 25.0
    assert result["forecast"]["available"] is False
    assert result["forecast"]["reason"] == "no_persisted_capacity_time_series"
    assert result["policy"]["evidence_deletion_allowed_to_make_room"] is False
    assert result["policy"]["history_truncation_allowed_to_make_room"] is False
    assert result["policy"]["quality_reduction_allowed_to_make_room"] is False
    assert result["safety"]["assumes_provider_quota"] is False
    assert result["safety"]["mutates_data"] is False


def test_capacity_headroom_keeps_missing_measurement_unknown(monkeypatch) -> None:
    monkeypatch.setattr(capacity, "get_settings", _settings)
    monkeypatch.setattr(
        capacity,
        "build_dashboard_snapshot",
        lambda: _dashboard_snapshot(supabase=None, safe=False),
    )

    result = capacity.build_capacity_headroom_snapshot()

    assert result["planning_status"] == "unknown"
    assert result["unknown_services"] == ["supabase"]
    supabase = next(row for row in result["services"] if row["service"] == "supabase")
    assert supabase["measurement_available"] is False
    assert supabase["usage_percent"] is None
    assert supabase["remaining_to_pause_threshold"] is None


def test_capacity_routes_reuse_dashboard_auth_and_are_read_only(monkeypatch) -> None:
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
        capacity_api,
        "build_capacity_headroom_snapshot",
        lambda: {
            "generated_at": "2026-09-18T04:00:00+00:00",
            "planning_status": "safe_headroom",
            "capacity_decision": {"safe": True, "reason": "ok", "blocking_services": []},
            "services": [],
            "forecast": {"available": False, "note": "no forecast"},
            "policy": {"action_when_threshold_reached": "pause_ingestion_and_expand_or_migrate_capacity"},
            "safety": {"read_only": True},
        },
    )

    assert client.get("/dashboard/capacity-plan").status_code == 401
    page = client.get("/dashboard/capacity-plan", auth=("operator", "secret"))
    status = client.get("/dashboard/capacity-plan/status", auth=("operator", "secret"))

    assert page.status_code == 200
    assert "Capacity Headroom Planner" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json()["planning_status"] == "safe_headroom"
