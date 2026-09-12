from datetime import UTC, datetime, timedelta

from app.monitoring.models import MonitorDefinition
from app.monitoring.scheduled_gate import assess_scheduled_monitor_gate


def _monitor(*, enabled: bool = True) -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=enabled,
    )


def test_disabled_monitor_never_becomes_due() -> None:
    decision = assess_scheduled_monitor_gate(
        _monitor(enabled=False),
        now=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        last_checked_at=None,
    )

    assert not decision.due
    assert decision.reason == "monitor_disabled"
    assert decision.next_eligible_at is None


def test_never_checked_monitor_is_due() -> None:
    decision = assess_scheduled_monitor_gate(
        _monitor(),
        now=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        last_checked_at=None,
    )

    assert decision.due
    assert decision.reason == "monitor_never_checked"
    assert decision.next_eligible_at is None


def test_recent_success_is_not_due_until_interval_expires() -> None:
    last = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    decision = assess_scheduled_monitor_gate(
        _monitor(),
        now=last + timedelta(minutes=30),
        last_checked_at=last,
        consecutive_failures=0,
    )

    assert not decision.due
    assert decision.reason == "monitor_not_due"
    assert decision.next_eligible_at == last + timedelta(hours=1)


def test_monitor_is_due_at_exact_eligible_time() -> None:
    last = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    decision = assess_scheduled_monitor_gate(
        _monitor(),
        now=last + timedelta(hours=1),
        last_checked_at=last,
        consecutive_failures=0,
    )

    assert decision.due
    assert decision.reason == "monitor_due"
    assert decision.next_eligible_at == last + timedelta(hours=1)


def test_failure_backoff_is_respected() -> None:
    last = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    decision = assess_scheduled_monitor_gate(
        _monitor(),
        now=last + timedelta(hours=1),
        last_checked_at=last,
        consecutive_failures=1,
    )

    assert not decision.due
    assert decision.reason == "monitor_not_due"
    assert decision.next_eligible_at == last + timedelta(hours=2)
