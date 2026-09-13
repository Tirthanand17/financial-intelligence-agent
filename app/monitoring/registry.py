from app.monitoring.models import MonitorDefinition
from app.sources.registry import validate_source_url


# Registry entries describe monitors that are approved/configured for source
# discovery. Whether monitoring may run at all is controlled separately by the
# global SOURCE_MONITORING_ENABLED safety gate, which remains false by default.
MONITORS: tuple[MonitorDefinition, ...] = (
    MonitorDefinition(
        monitor_id="rbi-press-releases-rss",
        source_id="rbi",
        url="https://rbi.org.in/pressreleases_rss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=10,
    ),
    MonitorDefinition(
        monitor_id="sebi-rss",
        source_id="sebi",
        url="https://www.sebi.gov.in/sebirss.xml",
        interval_minutes=60,
        enabled=True,
        max_new_documents_per_run=10,
    ),
    MonitorDefinition(
        monitor_id="nse-daily-buyback-rss",
        source_id="nse",
        url="https://nsearchives.nseindia.com/content/RSS/Daily_Buyback.xml",
        interval_minutes=60,
        enabled=True,
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
