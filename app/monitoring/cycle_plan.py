from dataclasses import dataclass
from datetime import datetime

from app.monitoring.models import MonitorDefinition
from app.monitoring.queue_retry import assess_discovery_retry
from app.monitoring.scheduled_gate import assess_scheduled_monitor_gate


@dataclass(frozen=True, slots=True)
class PendingRetryState:
    attempt_count: int
    last_attempt_at: datetime | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class RecurringCyclePlan:
    monitor_due: bool
    monitor_reason: str
    next_monitor_at: datetime | None
    fresh_eligible_count: int
    retry_eligible_count: int
    retry_deferred_count: int
    retry_blocked_count: int
    eligible_pending_count: int
    processing_limit: int
    planned_processing_count: int


def plan_recurring_cycle(
    monitor: MonitorDefinition,
    *,
    now: datetime,
    last_checked_at: datetime | None,
    consecutive_failures: int,
    pending_states: tuple[PendingRetryState, ...],
    processing_limit: int,
) -> RecurringCyclePlan:
    """Build a pure, read-only plan for one conservative recurring cycle.

    The first integrated recurring design gates the whole cycle behind the source
    monitor cadence. This prevents an early scheduler invocation from fetching
    either the feed or queued item URLs. When the monitor is due, only queue rows
    that are fresh or whose retry backoff has expired may be considered, and the
    processing count remains explicitly bounded.
    """
    if processing_limit < 1 or processing_limit > monitor.max_new_documents_per_run:
        raise ValueError("processing_limit must be between 1 and monitor maximum")

    monitor_gate = assess_scheduled_monitor_gate(
        monitor,
        now=now,
        last_checked_at=last_checked_at,
        consecutive_failures=consecutive_failures,
    )

    fresh = 0
    retry_due = 0
    retry_deferred = 0
    retry_blocked = 0
    for state in pending_states:
        decision = assess_discovery_retry(
            now=now,
            interval_minutes=monitor.interval_minutes,
            attempt_count=state.attempt_count,
            last_attempt_at=state.last_attempt_at,
            last_error_code=state.last_error_code,
        )
        if decision.reason == "discovery_ready":
            fresh += 1
        elif decision.reason == "retry_due":
            retry_due += 1
        elif decision.reason == "retry_backoff":
            retry_deferred += 1
        else:
            retry_blocked += 1

    eligible = fresh + retry_due
    planned = min(eligible, processing_limit) if monitor_gate.due else 0

    return RecurringCyclePlan(
        monitor_due=monitor_gate.due,
        monitor_reason=monitor_gate.reason,
        next_monitor_at=monitor_gate.next_eligible_at,
        fresh_eligible_count=fresh,
        retry_eligible_count=retry_due,
        retry_deferred_count=retry_deferred,
        retry_blocked_count=retry_blocked,
        eligible_pending_count=eligible,
        processing_limit=processing_limit,
        planned_processing_count=planned,
    )
