import sys
from pathlib import Path

from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.monitoring.registry import MONITORS, get_monitor, validate_monitor_registry
from app.monitoring.source_coverage import build_source_coverage, primary_india_monitoring_gaps
from app.sources.registry import TRUSTED_SOURCES
from app.storage.database import (
    ClaimTrustEventRecord,
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    get_session,
)

REQUIRED_MONITORS = {
    "rbi": "rbi-press-releases-rss",
    "sebi": "sebi-rss",
    "nse": "nse-daily-buyback-rss",
    "mospi": "mospi-latest-releases-api",
}
EXPANSION_SOURCES = ("sebi", "nse", "mospi")


def main() -> None:
    settings = get_settings()
    print("PHASE 15 MULTI-SOURCE CLOSEOUT READINESS - READ ONLY")
    print(f"SOURCE_MONITORING_ENABLED: {str(settings.source_monitoring_enabled).lower()}")
    print(f"SOURCE_AUTO_INGEST_ENABLED: {str(settings.source_auto_ingest_enabled).lower()}")
    print(f"TRUST_PROMOTION_ENABLED: {str(settings.trust_promotion_enabled).lower()}")

    blockers: list[str] = []
    if settings.source_monitoring_enabled:
        blockers.append("gate:source_monitoring_enabled")
    if settings.source_auto_ingest_enabled:
        blockers.append("gate:source_auto_ingest_enabled")
    if settings.trust_promotion_enabled:
        blockers.append("gate:trust_promotion_enabled")

    try:
        validate_monitor_registry()
        for source_id, monitor_id in REQUIRED_MONITORS.items():
            monitor = get_monitor(monitor_id)
            if monitor.source_id != source_id:
                blockers.append(f"monitor:{source_id}:wrong_mapping")
    except ValueError:
        blockers.append("monitor:registry_invalid")

    coverage = build_source_coverage(TRUSTED_SOURCES, MONITORS)
    gaps = primary_india_monitoring_gaps(coverage)
    if gaps:
        blockers.append("coverage:india_authority_a_gap_remaining")

    print(f"TRUSTED SOURCES TOTAL: {len(coverage)}")
    print(f"MONITORED SOURCES TOTAL: {sum(row.monitored for row in coverage)}")
    print(
        "REMAINING INDIA AUTHORITY-A GAPS: "
        + (",".join(row.source_id for row in gaps) if gaps else "-")
    )

    with get_session() as session:
        for source_id in EXPANSION_SOURCES:
            monitor_id = REQUIRED_MONITORS[source_id]
            record = session.scalar(
                select(SourceMonitorDiscoveryRecord)
                .where(
                    SourceMonitorDiscoveryRecord.monitor_id == monitor_id,
                    SourceMonitorDiscoveryRecord.source_id == source_id,
                    SourceMonitorDiscoveryRecord.status.in_(("ingested", "duplicate")),
                    SourceMonitorDiscoveryRecord.document_id.is_not(None),
                )
                .order_by(SourceMonitorDiscoveryRecord.last_attempt_at.desc())
                .limit(1)
            )
            if record is None:
                blockers.append(f"canary:{source_id}:missing_terminal_discovery")
                print(f"CANARY {source_id}: missing")
                continue
            document = session.get(DocumentRecord, record.document_id)
            if document is None:
                blockers.append(f"canary:{source_id}:linked_document_missing")
                print(f"CANARY {source_id}: linked_document_missing")
                continue
            if document.source_id != source_id:
                blockers.append(f"canary:{source_id}:document_source_mismatch")
            if not document.sha256 or document.chunk_count < 1:
                blockers.append(f"canary:{source_id}:document_integrity_invalid")
            print(
                f"CANARY {source_id}: status={record.status} "
                f"publication_date={record.publication_date or '-'} "
                f"sha256={document.sha256} chunks={document.chunk_count}"
            )

        trust_events = session.scalar(
            select(func.count()).select_from(ClaimTrustEventRecord)
        )
        print(f"TRUST EVENTS TOTAL: {trust_events}")
        if trust_events != 0:
            blockers.append("trust:unexpected_promotion_event")

    if blockers:
        print(
            "FINAL: BLOCKED - Phase 15 closeout invariants are not satisfied. "
            f"blockers={','.join(dict.fromkeys(blockers))}"
        )
        return
    print(
        "FINAL: PASS-READ-ONLY - all India Authority-A sources are monitored, "
        "SEBI/NSE/MoSPI each have a linked controlled canary document, all global "
        "automation/trust gates remain false, and no trust promotion event exists."
    )


if __name__ == "__main__":
    main()
