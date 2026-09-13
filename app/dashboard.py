from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import get_settings
from app.monitoring.measurements import CloudBudgetLimits, assess_measured_capacity, measure_cloud_usage
from app.storage.database import (
    ClaimRecord,
    ClaimTrustEventRecord,
    DocumentRecord,
    SourceMonitorDiscoveryRecord,
    SourceMonitorRunRecord,
    SourceMonitorStateRecord,
    get_session,
)
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def build_dashboard_snapshot() -> dict[str, object]:
    """Build a secret-free, read-only operational snapshot for the dashboard."""
    settings = get_settings()

    with get_session() as session:
        documents = _count(session, DocumentRecord)
        claims = _count(session, ClaimRecord)
        trust_events = _count(session, ClaimTrustEventRecord)
        expected_qdrant_points = int(
            session.scalar(select(func.coalesce(func.sum(DocumentRecord.chunk_count), 0))) or 0
        )

        monitor_states = list(
            session.scalars(select(SourceMonitorStateRecord).order_by(SourceMonitorStateRecord.source_id))
        )
        discoveries = list(session.scalars(select(SourceMonitorDiscoveryRecord.status)))
        latest_runs = list(
            session.scalars(
                select(SourceMonitorRunRecord)
                .order_by(SourceMonitorRunRecord.started_at.desc())
                .limit(20)
            )
        )

        usage = measure_cloud_usage(
            session,
            s3_client=get_s3_client(),
            qdrant_client=get_qdrant_client(),
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
        services, capacity = assess_measured_capacity(
            usage,
            CloudBudgetLimits(
                supabase_max_mb=settings.monitor_supabase_max_mb,
                backblaze_b2_max_mb=settings.monitor_b2_max_mb,
                qdrant_max_points=settings.monitor_qdrant_max_points,
                low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
            ),
        )

    discovery_counts = Counter(discoveries)
    qdrant_match = usage.qdrant_points == expected_qdrant_points
    monitors_ready = bool(monitor_states) and all(row.state == "ready" for row in monitor_states)
    unexpected_trust = trust_events > 0

    if not capacity.allow_ingestion or not qdrant_match or unexpected_trust:
        overall = "blocked"
    elif not monitors_ready or any(row.outcome == "failed" for row in latest_runs[:4]):
        overall = "warning"
    else:
        overall = "healthy"

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "runtime_gates": {
            "source_monitoring_enabled": settings.source_monitoring_enabled,
            "source_auto_ingest_enabled": settings.source_auto_ingest_enabled,
            "trust_promotion_enabled": settings.trust_promotion_enabled,
        },
        "totals": {
            "documents": documents,
            "claims": claims,
            "trust_events": trust_events,
            "expected_qdrant_points": expected_qdrant_points,
            "actual_qdrant_points": usage.qdrant_points,
            "qdrant_points_match": qdrant_match,
        },
        "queue": {
            "total": sum(discovery_counts.values()),
            "pending": discovery_counts.get("pending", 0),
            "ingested": discovery_counts.get("ingested", 0),
            "duplicate": discovery_counts.get("duplicate", 0),
            "rejected": discovery_counts.get("rejected", 0),
            "failed": discovery_counts.get("failed", 0),
        },
        "capacity": {
            "safe": capacity.allow_ingestion,
            "reason": capacity.reason,
            "blocking_services": list(capacity.blocking_services),
            "services": [
                {"service": row.service, "state": row.state.value, "detail": row.detail}
                for row in services
            ],
            "usage": {
                "supabase_bytes": usage.supabase_bytes,
                "backblaze_b2_bytes": usage.backblaze_b2_bytes,
                "qdrant_points": usage.qdrant_points,
            },
        },
        "monitors": [
            {
                "monitor_id": row.monitor_id,
                "source_id": row.source_id,
                "state": row.state,
                "reason": row.reason,
                "consecutive_failures": row.consecutive_failures,
                "last_checked_at": _iso(row.last_checked_at),
                "last_success_at": _iso(row.last_success_at),
            }
            for row in monitor_states
        ],
        "recent_runs": [
            {
                "monitor_id": row.monitor_id,
                "source_id": row.source_id,
                "outcome": row.outcome,
                "reason": row.reason,
                "discovered_count": row.discovered_count,
                "ingested_count": row.ingested_count,
                "duplicate_count": row.duplicate_count,
                "error_code": row.error_code,
                "started_at": _iso(row.started_at),
                "finished_at": _iso(row.finished_at),
            }
            for row in latest_runs
        ],
        "integrity_note": (
            "This dashboard performs live structural/Qdrant/capacity checks. Full evidence-hash "
            "verification remains the responsibility of the fail-closed production-readiness workflow."
        ),
    }
