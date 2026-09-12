from dataclasses import dataclass

from app.monitoring.models import CapacityDecision
from app.monitoring.probe import ManualFeedProbeResult


@dataclass(frozen=True, slots=True)
class MonitorReadinessDecision:
    """Readiness summary for enabling one bounded source monitor.

    This policy never changes runtime flags. It only explains whether the
    prerequisites for observation are satisfied. Auto-ingestion and TRUSTED
    promotion remain independent gates and are intentionally outside this
    decision.
    """

    ready: bool
    reason: str
    blockers: tuple[str, ...] = ()


def evaluate_monitor_readiness(
    *,
    capacity: CapacityDecision,
    probe: ManualFeedProbeResult,
    source_monitoring_enabled: bool,
) -> MonitorReadinessDecision:
    blockers: list[str] = []

    if not capacity.allow_ingestion:
        blockers.append(f"capacity:{capacity.reason}")

    if probe.status != "ok":
        blockers.append(f"feed:{probe.reason}")
    elif probe.discovered_count < 1:
        blockers.append("feed:no_allowlisted_items")

    if not source_monitoring_enabled:
        blockers.append("gate:source_monitoring_disabled")

    if blockers:
        return MonitorReadinessDecision(
            ready=False,
            reason="monitor_not_ready",
            blockers=tuple(blockers),
        )

    return MonitorReadinessDecision(
        ready=True,
        reason="monitor_prerequisites_satisfied",
    )
