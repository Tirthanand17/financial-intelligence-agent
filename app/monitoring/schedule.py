from datetime import datetime, timedelta

from app.monitoring.models import MonitorDefinition


_MAX_FAILURE_BACKOFF_HOURS = 24


def next_check_at(
    monitor: MonitorDefinition,
    *,
    last_checked_at: datetime | None,
    consecutive_failures: int = 0,
) -> datetime | None:
    """Return the next eligible check time for one monitor.

    A never-checked monitor is immediately due (`None` means no prior schedule
    barrier). Normal cadence is the configured interval. Consecutive failures use
    exponential backoff capped at 24 hours so broken/blocked sources are not
    hammered repeatedly.
    """
    if consecutive_failures < 0:
        raise ValueError("consecutive_failures cannot be negative")
    if last_checked_at is None:
        return None

    base = timedelta(minutes=monitor.interval_minutes)
    if consecutive_failures == 0:
        delay = base
    else:
        multiplier = 2 ** min(consecutive_failures, 16)
        delay = min(
            base * multiplier,
            timedelta(hours=_MAX_FAILURE_BACKOFF_HOURS),
        )

    return last_checked_at + delay


def is_monitor_due(
    monitor: MonitorDefinition,
    *,
    now: datetime,
    last_checked_at: datetime | None,
    consecutive_failures: int = 0,
) -> bool:
    due_at = next_check_at(
        monitor,
        last_checked_at=last_checked_at,
        consecutive_failures=consecutive_failures,
    )
    return due_at is None or now >= due_at
