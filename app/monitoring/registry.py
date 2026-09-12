from app.monitoring.models import MonitorDefinition
from app.sources.registry import validate_source_url


MONITORS: tuple[MonitorDefinition, ...] = (
    MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=False,
        max_new_documents_per_run=10,
    ),
)


def get_monitor(monitor_id: str) -> MonitorDefinition:
    for monitor in MONITORS:
        if monitor.monitor_id == monitor_id:
            validate_source_url(monitor.source_id, monitor.url)
            return monitor
    raise ValueError(f"Unknown monitor: {monitor_id}")


def validate_monitor_registry() -> None:
    seen: set[str] = set()
    for monitor in MONITORS:
        if monitor.monitor_id in seen:
            raise ValueError(f"Duplicate monitor_id: {monitor.monitor_id}")
        seen.add(monitor.monitor_id)
        validate_source_url(monitor.source_id, monitor.url)
