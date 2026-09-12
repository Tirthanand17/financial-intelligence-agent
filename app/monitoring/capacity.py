from collections.abc import Iterable

from app.monitoring.models import (
    CapacityDecision,
    CapacityState,
    ServiceCapacity,
)


_REQUIRED_CAPACITY_SERVICES = ("supabase", "backblaze_b2", "qdrant")


def evaluate_capacity(
    snapshots: Iterable[ServiceCapacity],
) -> CapacityDecision:
    """Fail closed unless every required cloud service reports safe capacity.

    Knowledge is never deleted, truncated, or silently skipped to make room.
    LOW, EXHAUSTED, UNKNOWN, or a missing required capacity signal pauses new
    ingestion so an operator can measure, deduplicate, compress, tier, or migrate
    storage without sacrificing provenance/history.
    """
    by_service = {snapshot.service: snapshot for snapshot in snapshots}

    missing = sorted(
        service
        for service in _REQUIRED_CAPACITY_SERVICES
        if service not in by_service
    )
    if missing:
        return CapacityDecision(
            allow_ingestion=False,
            reason="required_capacity_signal_missing",
            blocking_services=tuple(missing),
        )

    blocking = sorted(
        service
        for service in _REQUIRED_CAPACITY_SERVICES
        if by_service[service].state is not CapacityState.OK
    )
    if blocking:
        states = {by_service[service].state for service in blocking}
        if CapacityState.EXHAUSTED in states:
            reason = "cloud_capacity_exhausted"
        elif CapacityState.LOW in states:
            reason = "cloud_capacity_low"
        else:
            reason = "cloud_capacity_unknown"
        return CapacityDecision(
            allow_ingestion=False,
            reason=reason,
            blocking_services=tuple(blocking),
        )

    return CapacityDecision(
        allow_ingestion=True,
        reason="all_required_cloud_capacity_ok",
    )
