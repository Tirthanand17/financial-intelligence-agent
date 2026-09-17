from __future__ import annotations

from collections import defaultdict

from app.dashboard import build_dashboard_snapshot


EXPECTED_RUNTIME_GATES = {
    "source_monitoring_enabled": False,
    "source_auto_ingest_enabled": False,
    "trust_promotion_enabled": False,
}


def build_readiness_snapshot() -> dict[str, object]:
    """Build a read-only operator-focused readiness summary.

    This function reuses the existing dashboard snapshot so it does not introduce
    a second set of cloud probes or mutate any operational state.
    """
    snapshot = build_dashboard_snapshot()
    totals = snapshot["totals"]
    queue = snapshot["queue"]
    capacity = snapshot["capacity"]
    runtime_gates = snapshot["runtime_gates"]
    monitors = snapshot["monitors"]
    recent_runs = snapshot["recent_runs"]

    monitor_failures = [
        row for row in monitors if row["state"] != "ready" or row["consecutive_failures"] > 0
    ]
    recent_failed_runs = [row for row in recent_runs if row["outcome"] == "failed"]
    gate_drift = {
        key: runtime_gates.get(key)
        for key, expected in EXPECTED_RUNTIME_GATES.items()
        if runtime_gates.get(key) is not expected
    }

    latest_success_by_source: dict[str, str | None] = defaultdict(lambda: None)
    for row in recent_runs:
        if row["outcome"] != "success":
            continue
        source_id = str(row["source_id"])
        if latest_success_by_source[source_id] is None:
            latest_success_by_source[source_id] = row["finished_at"] or row["started_at"]

    service_usage = capacity["usage"]
    cloud_checks = {
        "supabase_measurement_available": service_usage.get("supabase_bytes") is not None,
        "backblaze_b2_measurement_available": service_usage.get("backblaze_b2_bytes") is not None,
        "qdrant_measurement_available": service_usage.get("qdrant_points") is not None,
        "qdrant_points_match": bool(totals["qdrant_points_match"]),
    }

    checks = {
        "capacity_safe": bool(capacity["safe"]),
        "qdrant_points_match": bool(totals["qdrant_points_match"]),
        "unexpected_trust_events_absent": int(totals["trust_events"]) == 0,
        "all_monitors_ready": bool(monitors) and not monitor_failures,
        "runtime_gates_at_safe_defaults": not gate_drift,
        "queue_has_no_failed_items": int(queue.get("failed", 0)) == 0,
        "recent_monitor_runs_have_no_failures": not recent_failed_runs,
        "cloud_measurements_available": all(cloud_checks.values()),
    }

    blocking = [name for name, passed in checks.items() if not passed]
    return {
        "generated_at": snapshot["generated_at"],
        "mode": "read_only_operational_readiness",
        "overall_status": snapshot["overall_status"],
        "checks": checks,
        "blocking_or_attention_checks": blocking,
        "cloud_checks": cloud_checks,
        "runtime_gates": runtime_gates,
        "gate_drift": gate_drift,
        "totals": totals,
        "queue": queue,
        "capacity": capacity,
        "monitors": monitors,
        "latest_success_by_source": dict(sorted(latest_success_by_source.items())),
        "recent_runs": recent_runs[:12],
        "integrity_note": snapshot["integrity_note"],
        "safety": {
            "mutates_data": False,
            "runs_ingestion": False,
            "changes_runtime_gates": False,
            "changes_trust_state": False,
            "note": (
                "This panel only summarizes the existing read-only dashboard snapshot. "
                "It cannot repair, delete, ingest, promote trust, or change scheduler state."
            ),
        },
    }
