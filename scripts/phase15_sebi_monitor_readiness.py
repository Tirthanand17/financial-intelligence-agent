import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.registry import MONITORS, get_monitor, validate_monitor_registry
from app.monitoring.source_coverage import build_source_coverage, primary_india_monitoring_gaps
from app.sources.registry import TRUSTED_SOURCES, validate_source_url


MONITOR_ID = "sebi-rss"
EXPECTED_URL = "https://www.sebi.gov.in/sebirss.xml"


def main() -> None:
    settings = get_settings()

    print("PHASE 15 SEBI MONITOR REGISTRATION READINESS - READ ONLY")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    if settings.source_monitoring_enabled:
        print("FINAL: BLOCKED - SOURCE_MONITORING_ENABLED must remain false for readiness.")
        return
    if settings.source_auto_ingest_enabled:
        print("FINAL: BLOCKED - SOURCE_AUTO_INGEST_ENABLED must remain false for readiness.")
        return
    if settings.trust_promotion_enabled:
        print("FINAL: BLOCKED - TRUST_PROMOTION_ENABLED must remain false for readiness.")
        return

    try:
        validate_monitor_registry()
        monitor = get_monitor(MONITOR_ID)
        validate_source_url(monitor.source_id, monitor.url)
    except ValueError as exc:
        print(f"FINAL: BLOCKED - monitor/source policy validation failed. error={type(exc).__name__}")
        return

    blockers: list[str] = []
    if monitor.source_id != "sebi":
        blockers.append("monitor:wrong_source")
    if monitor.url != EXPECTED_URL:
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

    sebi_row = by_id.get("sebi")
    if sebi_row is None or sebi_row.monitor_ids != (MONITOR_ID,):
        blockers.append("coverage:sebi_monitor_mapping_invalid")

    gap_ids = tuple(row.source_id for row in gaps)
    if gap_ids != ("nse", "mospi"):
        blockers.append("coverage:unexpected_primary_gap_set")

    print(
        "SEBI MONITOR: "
        f"id={monitor.monitor_id} source={monitor.source_id} url={monitor.url} "
        f"interval_minutes={monitor.interval_minutes} max_new_documents_per_run={monitor.max_new_documents_per_run}"
    )
    print(f"TRUSTED SOURCES TOTAL: {len(coverage)}")
    print(f"MONITORED SOURCES TOTAL: {len(monitored)}")
    print(
        "REMAINING INDIA AUTHORITY-A GAPS: "
        + (",".join(gap_ids) if gap_ids else "-")
    )

    if blockers:
        print(
            "FINAL: BLOCKED - SEBI monitor registration is not ready. blockers="
            + ",".join(blockers)
        )
        return

    print(
        "FINAL: PASS-READ-ONLY - SEBI RSS is registered as one bounded allow-listed monitor "
        "behind the global monitoring gate. No network request and no PostgreSQL/Backblaze B2/Qdrant "
        "write was performed. NSE and MoSPI remain unregistered primary expansion gaps."
    )


if __name__ == "__main__":
    main()
