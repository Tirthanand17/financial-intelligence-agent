import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.registry import MONITORS, get_monitor, validate_monitor_registry
from app.monitoring.source_coverage import build_source_coverage, primary_india_monitoring_gaps
from app.sources.mospi import MOSPI_LATEST_RELEASES_API_URL
from app.sources.registry import TRUSTED_SOURCES, validate_source_url

MONITOR_ID = "mospi-latest-releases-api"


def main() -> None:
    settings = get_settings()
    print("PHASE 15 MOSPI MONITOR REGISTRATION READINESS - READ ONLY")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")
    if (
        settings.source_monitoring_enabled
        or settings.source_auto_ingest_enabled
        or settings.trust_promotion_enabled
    ):
        print("FINAL: BLOCKED - all global monitoring/auto-ingest/trust gates must remain false.")
        return

    try:
        validate_monitor_registry()
        monitor = get_monitor(MONITOR_ID)
        validate_source_url(monitor.source_id, monitor.url)
    except ValueError as exc:
        print(f"FINAL: BLOCKED - monitor/source policy validation failed. error={type(exc).__name__}")
        return

    blockers: list[str] = []
    if monitor.source_id != "mospi":
        blockers.append("monitor:wrong_source")
    if monitor.url != MOSPI_LATEST_RELEASES_API_URL:
        blockers.append("monitor:unexpected_url")
    if monitor.interval_minutes < 60:
        blockers.append("monitor:interval_too_fast")
    if monitor.max_new_documents_per_run != 10:
        blockers.append("monitor:unexpected_discovery_bound")
    if not monitor.enabled:
        blockers.append("monitor:not_enabled_in_registry")

    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    monitored = tuple(row for row in coverage if row.monitored)
    gaps = primary_india_monitoring_gaps(coverage)
    by_id = {row.source_id: row for row in coverage}
    mospi_row = by_id.get("mospi")
    if mospi_row is None or mospi_row.monitor_ids != (MONITOR_ID,):
        blockers.append("coverage:mospi_monitor_mapping_invalid")
    gap_ids = tuple(row.source_id for row in gaps)
    if gap_ids:
        blockers.append("coverage:primary_india_gap_remaining")

    print(
        "MOSPI MONITOR: "
        f"id={monitor.monitor_id} source={monitor.source_id} url={monitor.url} "
        f"interval_minutes={monitor.interval_minutes} "
        f"max_new_documents_per_run={monitor.max_new_documents_per_run}"
    )
    print(f"TRUSTED SOURCES TOTAL: {len(coverage)}")
    print(f"MONITORED SOURCES TOTAL: {len(monitored)}")
    print("REMAINING INDIA AUTHORITY-A GAPS: " + (",".join(gap_ids) if gap_ids else "-"))
    if blockers:
        print("FINAL: BLOCKED - MoSPI monitor registration is not ready. blockers=" + ",".join(blockers))
        return
    print(
        "FINAL: PASS-READ-ONLY - MoSPI latest releases is registered as one bounded "
        "first-party monitor behind the global gate. No network request or PostgreSQL/"
        "Backblaze B2/Qdrant write was performed; India Authority-A coverage has no gaps."
    )


if __name__ == "__main__":
    main()
