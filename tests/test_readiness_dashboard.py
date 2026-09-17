from fastapi.testclient import TestClient

import app.api.dashboard as dashboard_api
import app.api.readiness_dashboard as readiness_api
import app.services.readiness as readiness
from app.main import app


client = TestClient(app)


def _base_snapshot() -> dict[str, object]:
    return {
        "generated_at": "2026-09-17T08:00:00+00:00",
        "overall_status": "healthy",
        "runtime_gates": {
            "source_monitoring_enabled": False,
            "source_auto_ingest_enabled": False,
            "trust_promotion_enabled": False,
        },
        "totals": {
            "documents": 19,
            "claims": 40,
            "trust_events": 0,
            "expected_qdrant_points": 53,
            "actual_qdrant_points": 53,
            "qdrant_points_match": True,
        },
        "queue": {
            "total": 30,
            "pending": 20,
            "ingested": 8,
            "duplicate": 2,
            "rejected": 0,
            "failed": 0,
        },
        "capacity": {
            "safe": True,
            "reason": "within_limits",
            "blocking_services": [],
            "services": [],
            "usage": {
                "supabase_bytes": 1024,
                "backblaze_b2_bytes": 2048,
                "qdrant_points": 53,
            },
        },
        "monitors": [
            {
                "monitor_id": "rbi-press-releases-rss",
                "source_id": "rbi",
                "state": "ready",
                "reason": "ok",
                "consecutive_failures": 0,
                "last_checked_at": "2026-09-17T07:30:00+00:00",
                "last_success_at": "2026-09-17T07:30:00+00:00",
            }
        ],
        "recent_runs": [
            {
                "monitor_id": "rbi-press-releases-rss",
                "source_id": "rbi",
                "outcome": "success",
                "reason": "ok",
                "discovered_count": 10,
                "ingested_count": 1,
                "duplicate_count": 0,
                "error_code": None,
                "started_at": "2026-09-17T07:25:00+00:00",
                "finished_at": "2026-09-17T07:30:00+00:00",
            }
        ],
        "integrity_note": "full hash verification remains in readiness workflow",
    }


def test_readiness_snapshot_is_read_only_and_passes_safe_baseline(monkeypatch) -> None:
    monkeypatch.setattr(readiness, "build_dashboard_snapshot", _base_snapshot)

    result = readiness.build_readiness_snapshot()

    assert result["mode"] == "read_only_operational_readiness"
    assert result["blocking_or_attention_checks"] == []
    assert all(result["checks"].values())
    assert result["latest_success_by_source"]["rbi"] == "2026-09-17T07:30:00+00:00"
    assert result["safety"] == {
        "mutates_data": False,
        "runs_ingestion": False,
        "changes_runtime_gates": False,
        "changes_trust_state": False,
        "note": (
            "This panel only summarizes the existing read-only dashboard snapshot. "
            "It cannot repair, delete, ingest, promote trust, or change scheduler state."
        ),
    }


def test_readiness_snapshot_surfaces_gate_drift_and_integrity_attention(monkeypatch) -> None:
    snapshot = _base_snapshot()
    snapshot["runtime_gates"] = {
        "source_monitoring_enabled": True,
        "source_auto_ingest_enabled": False,
        "trust_promotion_enabled": False,
    }
    snapshot["totals"] = {**snapshot["totals"], "qdrant_points_match": False}
    monkeypatch.setattr(readiness, "build_dashboard_snapshot", lambda: snapshot)

    result = readiness.build_readiness_snapshot()

    assert result["checks"]["runtime_gates_at_safe_defaults"] is False
    assert result["checks"]["qdrant_points_match"] is False
    assert result["gate_drift"] == {"source_monitoring_enabled": True}
    assert "runtime_gates_at_safe_defaults" in result["blocking_or_attention_checks"]
    assert "qdrant_points_match" in result["blocking_or_attention_checks"]


def test_readiness_routes_reuse_dashboard_auth_and_stay_read_only(monkeypatch) -> None:
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
        readiness_api,
        "build_readiness_snapshot",
        lambda: {
            "generated_at": "2026-09-17T08:00:00+00:00",
            "overall_status": "healthy",
            "checks": {},
            "cloud_checks": {},
            "runtime_gates": {},
            "totals": {
                "documents": 19,
                "claims": 40,
                "trust_events": 0,
                "expected_qdrant_points": 53,
                "actual_qdrant_points": 53,
            },
            "queue": {"pending": 0},
            "capacity": {"safe": True},
            "monitors": [],
            "recent_runs": [],
            "integrity_note": "read-only",
            "safety": {"note": "read-only"},
        },
    )

    assert client.get("/dashboard/readiness").status_code == 401
    page = client.get("/dashboard/readiness", auth=("operator", "secret"))
    status = client.get("/dashboard/readiness/status", auth=("operator", "secret"))

    assert page.status_code == 200
    assert "Operational Readiness" in page.text
    assert "/ingest" not in page.text
    assert "method=\"post\"" not in page.text.lower()
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.headers["x-frame-options"] == "DENY"
