import pytest

from app.monitoring.capacity import evaluate_capacity
from app.monitoring.models import CapacityState, MonitorDefinition, MonitorState, ServiceCapacity
from app.monitoring.policy import decide_monitor_run
from app.monitoring.registry import get_monitor, validate_monitor_registry


def _safe_capacity():
    return evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.OK),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )


def _monitor(*, enabled: bool = True) -> MonitorDefinition:
    return MonitorDefinition(
        monitor_id="test-rbi",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=enabled,
        max_new_documents_per_run=10,
    )


def test_all_required_capacity_signals_allow_ingestion() -> None:
    decision = _safe_capacity()

    assert decision.allow_ingestion is True
    assert decision.reason == "all_required_cloud_capacity_ok"
    assert decision.blocking_services == ()


def test_missing_capacity_signal_pauses_ingestion() -> None:
    decision = evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.OK),
        ]
    )

    assert decision.allow_ingestion is False
    assert decision.reason == "required_capacity_signal_missing"
    assert decision.blocking_services == ("qdrant",)


def test_low_capacity_pauses_instead_of_deleting_or_skipping_history() -> None:
    decision = evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.LOW),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )

    assert decision.allow_ingestion is False
    assert decision.reason == "cloud_capacity_low"
    assert decision.blocking_services == ("backblaze_b2",)


def test_exhausted_capacity_has_priority_reason() -> None:
    decision = evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.LOW),
            ServiceCapacity("backblaze_b2", CapacityState.EXHAUSTED),
            ServiceCapacity("qdrant", CapacityState.UNKNOWN),
        ]
    )

    assert decision.allow_ingestion is False
    assert decision.reason == "cloud_capacity_exhausted"
    assert set(decision.blocking_services) == {"supabase", "backblaze_b2", "qdrant"}


def test_disabled_monitor_never_becomes_ready() -> None:
    decision = decide_monitor_run(_monitor(enabled=False), _safe_capacity())

    assert decision.state is MonitorState.DISABLED
    assert decision.reason == "monitor_disabled"


def test_enabled_monitor_pauses_when_capacity_is_not_safe() -> None:
    capacity = evaluate_capacity(
        [
            ServiceCapacity("supabase", CapacityState.OK),
            ServiceCapacity("backblaze_b2", CapacityState.LOW),
            ServiceCapacity("qdrant", CapacityState.OK),
        ]
    )
    decision = decide_monitor_run(_monitor(enabled=True), capacity)

    assert decision.state is MonitorState.PAUSED_CAPACITY
    assert decision.blocking_services == ("backblaze_b2",)


def test_enabled_monitor_is_ready_only_with_safe_capacity() -> None:
    decision = decide_monitor_run(_monitor(enabled=True), _safe_capacity())

    assert decision.state is MonitorState.READY
    assert decision.reason == "monitor_enabled_and_capacity_safe"


def test_monitor_frequency_and_per_run_volume_are_bounded() -> None:
    with pytest.raises(ValueError, match="at least 60 minutes"):
        MonitorDefinition(
            monitor_id="too-fast",
            source_id="rbi",
            url="https://rbi.org.in/pressreleases_rss.xml",
            interval_minutes=15,
        )

    with pytest.raises(ValueError, match="remain bounded"):
        MonitorDefinition(
            monitor_id="too-large",
            source_id="rbi",
            url="https://rbi.org.in/pressreleases_rss.xml",
            interval_minutes=60,
            max_new_documents_per_run=101,
        )


def test_monitor_registry_is_allowlisted_and_disabled_by_default() -> None:
    validate_monitor_registry()
    monitor = get_monitor("rbi-press-releases-rss")

    assert monitor.source_id == "rbi"
    assert monitor.enabled is False
    assert monitor.interval_minutes == 60
