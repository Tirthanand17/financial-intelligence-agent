from datetime import UTC, datetime, timedelta

from app.monitoring.cycle_plan import PendingRetryState, plan_recurring_cycle
from app.monitoring.models import MonitorDefinition


def _monitor() -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=10,
    )


def test_early_cycle_plans_no_processing_even_with_fresh_queue() -> None:
    now = datetime(2026, 9, 12, 12, 30, tzinfo=UTC)
    plan = plan_recurring_cycle(
        _monitor(),
        now=now,
        last_checked_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        consecutive_failures=0,
        pending_states=(PendingRetryState(0, None, None),),
        processing_limit=1,
    )

    assert plan.monitor_due is False
    assert plan.monitor_reason == "monitor_not_due"
    assert plan.eligible_pending_count == 1
    assert plan.planned_processing_count == 0


def test_due_cycle_bounds_fresh_processing() -> None:
    now = datetime(2026, 9, 12, 13, 0, tzinfo=UTC)
    states = tuple(PendingRetryState(0, None, None) for _ in range(5))
    plan = plan_recurring_cycle(
        _monitor(),
        now=now,
        last_checked_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        consecutive_failures=0,
        pending_states=states,
        processing_limit=2,
    )

    assert plan.monitor_due is True
    assert plan.fresh_eligible_count == 5
    assert plan.planned_processing_count == 2


def test_backed_off_failure_is_not_counted_as_eligible() -> None:
    now = datetime(2026, 9, 12, 13, 0, tzinfo=UTC)
    failed_at = now - timedelta(minutes=30)
    plan = plan_recurring_cycle(
        _monitor(),
        now=now,
        last_checked_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        consecutive_failures=0,
        pending_states=(
            PendingRetryState(0, None, None),
            PendingRetryState(1, failed_at, "transient_network_error"),
        ),
        processing_limit=2,
    )

    assert plan.monitor_due is True
    assert plan.fresh_eligible_count == 1
    assert plan.retry_deferred_count == 1
    assert plan.eligible_pending_count == 1
    assert plan.planned_processing_count == 1
