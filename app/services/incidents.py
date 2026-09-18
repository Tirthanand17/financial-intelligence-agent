from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.readiness import build_readiness_snapshot


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}


def _incident(
    code: str,
    severity: str,
    title: str,
    detail: str,
    *,
    source_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "source_id": source_id,
        "evidence": evidence or {},
    }


def build_incident_snapshot() -> dict[str, object]:
    """Derive operator incidents from the existing fail-closed readiness snapshot.

    This is deliberately a projection only: no repair, notification delivery,
    ingestion, state transition, or cloud write is performed here.
    """
    readiness = build_readiness_snapshot()
    checks = readiness["checks"]
    totals = readiness["totals"]
    queue = readiness["queue"]
    capacity = readiness["capacity"]
    gate_drift = readiness["gate_drift"]
    cloud_checks = readiness["cloud_checks"]
    monitors = readiness["monitors"]
    recent_runs = readiness["recent_runs"]

    incidents: list[dict[str, object]] = []

    if not checks.get("capacity_safe", False):
        incidents.append(
            _incident(
                "CAPACITY_UNSAFE",
                "critical",
                "Storage/vector capacity is not safe",
                "At least one configured capacity measurement is low, exhausted, unknown, or unavailable. Ingestion should remain fail-closed.",
                evidence={"capacity": capacity},
            )
        )

    if not checks.get("qdrant_points_match", False):
        incidents.append(
            _incident(
                "QDRANT_POINT_MISMATCH",
                "critical",
                "Qdrant point count does not reconcile",
                "Expected and actual Qdrant point counts differ. Do not treat vector state as reconciled until investigated.",
                evidence={
                    "expected_qdrant_points": totals.get("expected_qdrant_points"),
                    "actual_qdrant_points": totals.get("actual_qdrant_points"),
                },
            )
        )

    trust_events = int(totals.get("trust_events", 0))
    if trust_events != 0:
        incidents.append(
            _incident(
                "UNEXPECTED_TRUST_EVENTS",
                "critical",
                "Unexpected trust events exist",
                "Trust promotion is expected to remain disabled during the current operating policy.",
                evidence={"trust_events": trust_events},
            )
        )

    if gate_drift:
        incidents.append(
            _incident(
                "RUNTIME_GATE_DRIFT",
                "critical",
                "Runtime safety gates differ from safe defaults",
                "One or more global runtime gates are not at the expected disabled defaults outside the bounded scheduler step.",
                evidence={"gate_drift": gate_drift},
            )
        )

    missing_cloud = [name for name, value in cloud_checks.items() if not value]
    if missing_cloud:
        incidents.append(
            _incident(
                "CLOUD_MEASUREMENT_UNAVAILABLE",
                "high",
                "One or more cloud integrity measurements are unavailable",
                "Readiness requires cloud measurements to be available and reconciled; missing measurements are not treated as healthy.",
                evidence={"failed_cloud_checks": missing_cloud},
            )
        )

    failed_queue = int(queue.get("failed", 0))
    if failed_queue:
        incidents.append(
            _incident(
                "QUEUE_FAILED_ITEMS",
                "high",
                "Queue contains failed items",
                "Failed queue items require investigation; they are not silently discarded or treated as successfully ingested.",
                evidence={"failed_items": failed_queue},
            )
        )

    for monitor in monitors:
        source_id = str(monitor.get("source_id") or "unknown")
        state = str(monitor.get("state") or "unknown")
        consecutive_failures = int(monitor.get("consecutive_failures") or 0)
        if state != "ready" or consecutive_failures > 0:
            incidents.append(
                _incident(
                    "SOURCE_MONITOR_NOT_READY",
                    "high",
                    f"{source_id.upper()} source monitor needs attention",
                    "The persisted monitor state is not ready or it has consecutive failures.",
                    source_id=source_id,
                    evidence={
                        "state": state,
                        "consecutive_failures": consecutive_failures,
                        "last_success_at": monitor.get("last_success_at"),
                        "last_error_code": monitor.get("last_error_code"),
                    },
                )
            )

    failed_run_sources: set[str] = set()
    for run in recent_runs:
        if run.get("outcome") != "failed":
            continue
        source_id = str(run.get("source_id") or "unknown")
        if source_id in failed_run_sources:
            continue
        failed_run_sources.add(source_id)
        incidents.append(
            _incident(
                "RECENT_MONITOR_RUN_FAILED",
                "high",
                f"Recent {source_id.upper()} monitor run failed",
                "A recent persisted monitor execution has a failed outcome and should be inspected before increasing automation.",
                source_id=source_id,
                evidence={
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                    "error_code": run.get("error_code"),
                },
            )
        )

    incidents.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(str(item["severity"]), 99),
            str(item["code"]),
            str(item.get("source_id") or ""),
        )
    )

    critical_count = sum(1 for item in incidents if item["severity"] == "critical")
    high_count = sum(1 for item in incidents if item["severity"] == "high")
    if critical_count:
        status = "blocked"
    elif high_count:
        status = "attention"
    else:
        status = "clear"

    return {
        "generated_at": readiness.get("generated_at") or datetime.now(UTC).isoformat(),
        "mode": "read_only_incident_evaluator",
        "status": status,
        "summary": {
            "incidents": len(incidents),
            "critical": critical_count,
            "high": high_count,
            "medium": sum(1 for item in incidents if item["severity"] == "medium"),
            "notification_delivery_configured": False,
        },
        "incidents": incidents,
        "readiness_status": readiness.get("overall_status"),
        "blocking_or_attention_checks": readiness.get("blocking_or_attention_checks", []),
        "safety": {
            "read_only": True,
            "mutates_data": False,
            "repairs_state": False,
            "sends_external_notifications": False,
            "changes_scheduler": False,
            "changes_trust_state": False,
            "note": (
                "This incident center derives deterministic operator alerts from the existing readiness snapshot. "
                "External delivery is intentionally not configured without an explicitly approved channel/recipient."
            ),
        },
    }
