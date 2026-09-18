from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.dashboard import build_dashboard_snapshot


_MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class _CapacityInput:
    service: str
    used: int | None
    limit: int | None
    unit: str


def _service_plan(item: _CapacityInput, *, low_watermark_percent: int, state: str | None) -> dict[str, object]:
    if item.used is None or item.limit is None or item.limit <= 0:
        return {
            "service": item.service,
            "unit": item.unit,
            "state": state or "unknown",
            "measurement_available": item.used is not None,
            "ceiling_configured": item.limit is not None and item.limit > 0,
            "used": item.used,
            "ceiling": item.limit,
            "low_watermark_percent": low_watermark_percent,
            "pause_threshold": None,
            "remaining_to_pause_threshold": None,
            "remaining_to_ceiling": None,
            "usage_percent": None,
            "headroom_percent": None,
        }

    pause_threshold = (item.limit * (100 - low_watermark_percent)) // 100
    remaining_to_pause = max(0, pause_threshold - item.used)
    remaining_to_ceiling = max(0, item.limit - item.used)
    usage_percent = round((item.used / item.limit) * 100, 4)
    headroom_percent = round((remaining_to_ceiling / item.limit) * 100, 4)
    return {
        "service": item.service,
        "unit": item.unit,
        "state": state or "unknown",
        "measurement_available": True,
        "ceiling_configured": True,
        "used": item.used,
        "ceiling": item.limit,
        "low_watermark_percent": low_watermark_percent,
        "pause_threshold": pause_threshold,
        "remaining_to_pause_threshold": remaining_to_pause,
        "remaining_to_ceiling": remaining_to_ceiling,
        "usage_percent": usage_percent,
        "headroom_percent": headroom_percent,
    }


def build_capacity_headroom_snapshot() -> dict[str, object]:
    """Describe exact measured headroom against project safety ceilings.

    This is a read-only planning projection. It deliberately does not infer
    provider quotas or predict an exhaustion date because the project does not yet
    persist a trustworthy capacity time series. Unknown measurement/ceiling state
    remains unknown rather than being guessed.
    """
    snapshot = build_dashboard_snapshot()
    settings = get_settings()
    usage = snapshot["capacity"]["usage"]
    service_states = {
        str(row["service"]): str(row["state"])
        for row in snapshot["capacity"].get("services", [])
    }
    low_watermark = settings.monitor_capacity_low_watermark_percent

    inputs = (
        _CapacityInput(
            "supabase",
            usage.get("supabase_bytes"),
            settings.monitor_supabase_max_mb * _MIB
            if settings.monitor_supabase_max_mb is not None
            else None,
            "bytes",
        ),
        _CapacityInput(
            "backblaze_b2",
            usage.get("backblaze_b2_bytes"),
            settings.monitor_b2_max_mb * _MIB
            if settings.monitor_b2_max_mb is not None
            else None,
            "bytes",
        ),
        _CapacityInput(
            "qdrant",
            usage.get("qdrant_points"),
            settings.monitor_qdrant_max_points,
            "points",
        ),
    )
    services = [
        _service_plan(
            item,
            low_watermark_percent=low_watermark,
            state=service_states.get(item.service),
        )
        for item in inputs
    ]

    unknown_services = [
        row["service"]
        for row in services
        if not row["measurement_available"] or not row["ceiling_configured"]
    ]
    at_or_beyond_pause = [
        row["service"]
        for row in services
        if row["remaining_to_pause_threshold"] == 0
        and row["measurement_available"]
        and row["ceiling_configured"]
    ]

    if unknown_services:
        planning_status = "unknown"
    elif at_or_beyond_pause or not snapshot["capacity"]["safe"]:
        planning_status = "pause_required"
    else:
        planning_status = "safe_headroom"

    return {
        "generated_at": snapshot["generated_at"],
        "mode": "read_only_capacity_headroom_planner",
        "planning_status": planning_status,
        "capacity_decision": {
            "safe": bool(snapshot["capacity"]["safe"]),
            "reason": snapshot["capacity"]["reason"],
            "blocking_services": list(snapshot["capacity"]["blocking_services"]),
        },
        "services": services,
        "unknown_services": unknown_services,
        "at_or_beyond_pause_threshold": at_or_beyond_pause,
        "forecast": {
            "available": False,
            "reason": "no_persisted_capacity_time_series",
            "days_to_pause_threshold": None,
            "note": (
                "No exhaustion date is guessed. A time-based forecast requires a persisted, "
                "validated history of comparable capacity measurements."
            ),
        },
        "policy": {
            "low_watermark_percent": low_watermark,
            "evidence_deletion_allowed_to_make_room": False,
            "history_truncation_allowed_to_make_room": False,
            "quality_reduction_allowed_to_make_room": False,
            "action_when_threshold_reached": "pause_ingestion_and_expand_or_migrate_capacity",
        },
        "safety": {
            "read_only": True,
            "mutates_data": False,
            "changes_capacity_ceiling": False,
            "changes_scheduler": False,
            "deletes_evidence": False,
            "assumes_provider_quota": False,
            "note": (
                "Headroom is calculated only from live measured usage and the project's explicit safety ceilings. "
                "It does not alter provider resources or recommend deleting evidence."
            ),
        },
    }
