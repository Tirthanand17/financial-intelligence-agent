from datetime import UTC, datetime, timedelta

import pytest

from app.monitoring.models import MonitorDefinition
from app.monitoring.schedule import is_monitor_due, next_check_at


def _monitor() -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=True,
    )


def test_never_checked_monitor_is_due() -> None:
    now = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    assert is_monitor_due(
        _monitor(),
        now=now,
        last_checked_at=None,
    )


def test_normal_monitor_waits_for_configured_interval() -> None:
    last = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    assert next_check_at(_monitor(), last_checked_at=last) == last + timedelta(hours=1)
    assert not is_monitor_due(
        _monitor(),
        now=last + timedelta(minutes=59),
        last_checked_at=last,
    )
    assert is_monitor_due(
        _monitor(),
        now=last + timedelta(hours=1),
        last_checked_at=last,
    )


def test_failures_apply_exponential_backoff() -> None:
    last = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    assert next_check_at(
        _monitor(),
        last_checked_at=last,
        consecutive_failures=1,
    ) == last + timedelta(hours=2)
    assert next_check_at(
        _monitor(),
        last_checked_at=last,
        consecutive_failures=2,
    ) == last + timedelta(hours=4)


def test_failure_backoff_is_capped_at_24_hours() -> None:
    last = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    assert next_check_at(
        _monitor(),
        last_checked_at=last,
        consecutive_failures=20,
    ) == last + timedelta(hours=24)


def test_negative_failure_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        next_check_at(
            _monitor(),
            last_checked_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
            consecutive_failures=-1,
        )
