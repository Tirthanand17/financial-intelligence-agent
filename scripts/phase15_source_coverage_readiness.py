import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.registry import MONITORS
from app.monitoring.source_coverage import build_source_coverage, primary_india_monitoring_gaps
from app.sources.registry import TRUSTED_SOURCES


def main() -> None:
    settings = get_settings()

    print("PHASE 15 MULTI-SOURCE EXPANSION READINESS - READ ONLY")
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

    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    monitored = tuple(row for row in coverage if row.monitored)
    gaps = primary_india_monitoring_gaps(coverage)

    print(f"TRUSTED SOURCES TOTAL: {len(coverage)}")
    print(f"MONITORED SOURCES TOTAL: {len(monitored)}")
    print(f"UNMONITORED INDIA AUTHORITY-A SOURCES: {len(gaps)}")

    for row in coverage:
        monitors = ",".join(row.monitor_ids) or "-"
        print(
            "SOURCE: "
            f"id={row.source_id} authority={row.authority_level.value} "
            f"country={row.country or '-'} category={row.category} "
            f"monitored={str(row.monitored).lower()} monitors={monitors}"
        )

    print(
        "PRIMARY INDIA EXPANSION TARGETS: "
        + (",".join(row.source_id for row in gaps) if gaps else "-")
    )
    print(
        "FINAL: PASS-READ-ONLY - trusted-source monitoring coverage was inventoried "
        "without network access or PostgreSQL/Backblaze B2/Qdrant writes."
    )


if __name__ == "__main__":
    main()
