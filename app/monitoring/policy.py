from app.monitoring.models import (
    CapacityDecision,
    MonitorDecision,
    MonitorDefinition,
    MonitorState,
)


def decide_monitor_run(
    monitor: MonitorDefinition,
    capacity: CapacityDecision,
) -> MonitorDecision:
    """Decide whether one configured source monitor may attempt ingestion.

    This pure policy intentionally has no network/database side effects. Generic
    crawling is not permitted: only an explicitly configured monitor that is
    enabled and has safe cloud capacity can become READY.
    """
    if not monitor.enabled:
        return MonitorDecision(
            state=MonitorState.DISABLED,
            reason="monitor_disabled",
        )

    if not capacity.allow_ingestion:
        return MonitorDecision(
            state=MonitorState.PAUSED_CAPACITY,
            reason=capacity.reason,
            blocking_services=capacity.blocking_services,
        )

    return MonitorDecision(
        state=MonitorState.READY,
        reason="monitor_enabled_and_capacity_safe",
    )
