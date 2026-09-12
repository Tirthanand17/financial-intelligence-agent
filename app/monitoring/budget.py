from app.monitoring.models import CapacityState, ServiceCapacity


def assess_usage_budget(
    service: str,
    *,
    used: int | None,
    limit: int | None,
    low_watermark_percent: int = 10,
) -> ServiceCapacity:
    """Convert measured usage plus an operator-approved ceiling into capacity state.

    No provider quota is guessed. If the system cannot measure usage or no explicit
    safe ceiling is configured, capacity remains UNKNOWN and automatic ingestion
    will pause through the fail-closed capacity policy.
    """
    if not 1 <= low_watermark_percent <= 50:
        raise ValueError("low_watermark_percent must be between 1 and 50")
    if limit is None:
        return ServiceCapacity(service, CapacityState.UNKNOWN, "budget_not_configured")
    if limit <= 0:
        raise ValueError("capacity limit must be positive")
    if used is None:
        return ServiceCapacity(service, CapacityState.UNKNOWN, "usage_unavailable")
    if used < 0:
        raise ValueError("used capacity cannot be negative")

    if used >= limit:
        return ServiceCapacity(service, CapacityState.EXHAUSTED, "budget_exhausted")

    remaining = limit - used
    remaining_percent = (remaining * 100) / limit
    if remaining_percent <= low_watermark_percent:
        return ServiceCapacity(service, CapacityState.LOW, "budget_low")

    return ServiceCapacity(service, CapacityState.OK, "budget_ok")
