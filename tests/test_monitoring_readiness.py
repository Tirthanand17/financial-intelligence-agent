from app.monitoring.models import CapacityDecision
from app.monitoring.probe import ManualFeedProbeResult
from app.monitoring.readiness import evaluate_monitor_readiness


def _capacity(allowed: bool, reason: str = "all_required_cloud_capacity_ok") -> CapacityDecision:
    return CapacityDecision(
        allow_ingestion=allowed,
        reason=reason,
        blocking_services=() if allowed else ("supabase",),
    )


def _probe(*, status: str = "ok", discovered: int = 1, reason: str = "feed_probe_completed") -> ManualFeedProbeResult:
    return ManualFeedProbeResult(
        status=status,
        reason=reason,
        discovered_count=discovered,
    )


def test_ready_requires_capacity_feed_and_monitoring_gate() -> None:
    result = evaluate_monitor_readiness(
        capacity=_capacity(True),
        probe=_probe(),
        source_monitoring_enabled=True,
    )

    assert result.ready is True
    assert result.reason == "monitor_prerequisites_satisfied"
    assert result.blockers == ()


def test_unknown_capacity_blocks_readiness() -> None:
    result = evaluate_monitor_readiness(
        capacity=_capacity(False, "cloud_capacity_unknown"),
        probe=_probe(),
        source_monitoring_enabled=True,
    )

    assert result.ready is False
    assert "capacity:cloud_capacity_unknown" in result.blockers


def test_failed_feed_probe_blocks_readiness() -> None:
    result = evaluate_monitor_readiness(
        capacity=_capacity(True),
        probe=_probe(status="failed", reason="transient_network_error"),
        source_monitoring_enabled=True,
    )

    assert result.ready is False
    assert "feed:transient_network_error" in result.blockers


def test_zero_allowlisted_feed_items_blocks_readiness() -> None:
    result = evaluate_monitor_readiness(
        capacity=_capacity(True),
        probe=_probe(discovered=0),
        source_monitoring_enabled=True,
    )

    assert result.ready is False
    assert "feed:no_allowlisted_items" in result.blockers


def test_disabled_monitoring_gate_blocks_readiness() -> None:
    result = evaluate_monitor_readiness(
        capacity=_capacity(True),
        probe=_probe(),
        source_monitoring_enabled=False,
    )

    assert result.ready is False
    assert "gate:source_monitoring_disabled" in result.blockers


def test_multiple_blockers_are_preserved_for_operator_diagnostics() -> None:
    result = evaluate_monitor_readiness(
        capacity=_capacity(False, "cloud_capacity_unknown"),
        probe=_probe(discovered=0),
        source_monitoring_enabled=False,
    )

    assert result.blockers == (
        "capacity:cloud_capacity_unknown",
        "feed:no_allowlisted_items",
        "gate:source_monitoring_disabled",
    )
