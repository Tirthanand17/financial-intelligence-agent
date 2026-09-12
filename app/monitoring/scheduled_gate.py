from dataclasses import dataclass
from datetime import datetime

from app.monitoring.models import MonitorDefinition
from app.monitoring.schedule import next_check_at


@dataclass(frozen=True, slots=True)
class ScheduledMonitorGateDecision:
    due: bool
    reason: str
    next_eligible_at: datetime | None


def assess_scheduled_monitor_gate(
    monitor: MonitorDefinition,
    *,
    now: datetime,
    last_checked_at: datetime | None,
    consecutive_failures: int = 0,
) -> ScheduledMonitorGateDecision:
    """Decide whether a recurring monitor invocation may proceed now.

    This is deliberately pure: it performs no network or database writes. A
    never-checked monitor is immediately due. Otherwise the existing cadence and
    exponential-backoff policy determine the earliest eligible run time.
    """
    if not monitor.enabled:
        return ScheduledMonitorGateDecision(
            due=False,
            reason="monitor_disabled",
            next_eligible_at=None,
        )

    eligible_at = next_check_at(
        monitor,
        last_checked_at=last_checked_at,
        consecutive_failures=consecutive_failures,
    )
    if eligible_at is None:
        return ScheduledMonitorGateDecision(
            due=True,
            reason="monitor_never_checked",
            next_eligible_at=None,
        )

    if now < eligible_at:
        return ScheduledMonitorGateDecision(
            due=False,
            reason="monitor_not_due",
            next_eligible_at=eligible_at,
        )

    return ScheduledMonitorGateDecision(
        due=True,
        reason="monitor_due",
        next_eligible_at=eligible_at,
    )
