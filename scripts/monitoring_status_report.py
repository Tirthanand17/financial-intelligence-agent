import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.report import build_monitoring_status_report
from app.storage.database import get_session


def _format_counts(values: tuple[tuple[str, int], ...]) -> str:
    if not values:
        return "-"
    return ", ".join(f"{name}={count}" for name, count in values)


def main() -> None:
    settings = get_settings()

    with get_session() as session:
        report = build_monitoring_status_report(
            session,
            source_monitoring_enabled=settings.source_monitoring_enabled,
            source_auto_ingest_enabled=settings.source_auto_ingest_enabled,
        )

    print("PHASE 5 MONITORING STATUS - READ ONLY")
    print(f"SOURCE_MONITORING_ENABLED: {str(report.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(report.source_auto_ingest_enabled).lower()}")
    print(f"MONITOR STATES: {report.total_monitor_states} ({_format_counts(report.monitor_state_counts)})")
    print(f"MONITOR RUNS: {report.total_runs} ({_format_counts(report.run_outcome_counts)})")
    print(
        f"DISCOVERIES: {report.total_discoveries} "
        f"({_format_counts(report.discovery_status_counts)})"
    )
    print(f"PENDING DISCOVERIES: {report.pending_discoveries}")
    print("FINAL: READ-ONLY - no monitor, ingestion, claim, or trust state was changed.")


if __name__ == "__main__":
    main()
