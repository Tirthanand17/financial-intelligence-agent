from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.monitoring.budget import assess_usage_budget
from app.monitoring.models import CapacityDecision, ServiceCapacity
from app.monitoring.capacity import evaluate_capacity


_MIB = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CloudUsage:
    """Measured usage only; never provider-plan assumptions or guessed quotas."""

    supabase_bytes: int | None
    backblaze_b2_bytes: int | None
    qdrant_points: int | None


@dataclass(frozen=True, slots=True)
class CloudBudgetLimits:
    """Operator-approved ceilings used to convert measured usage into capacity."""

    supabase_max_mb: int | None
    backblaze_b2_max_mb: int | None
    qdrant_max_points: int | None
    low_watermark_percent: int = 10


def _measure_database_bytes(session: Session) -> int | None:
    try:
        value = session.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    except Exception:
        return None
    if value is None:
        return None
    size = int(value)
    return size if size >= 0 else None


def _measure_b2_bytes(client, bucket: str) -> int | None:
    """Sum metadata for every stored B2 object version without downloading bodies.

    Backblaze buckets can retain old versions after overwrites/deletes, and those
    versions still consume storage. Measuring only ``ListObjectsV2`` would count
    current objects and could understate real storage use. The B2 S3-compatible
    API supports ``ListObjectVersions``, so capacity accounting deliberately sums
    all returned ``Versions`` while ignoring zero-byte delete markers.
    """
    total = 0
    key_marker: str | None = None
    version_id_marker: str | None = None

    try:
        while True:
            kwargs: dict[str, object] = {"Bucket": bucket, "MaxKeys": 1000}
            if key_marker:
                kwargs["KeyMarker"] = key_marker
            if version_id_marker:
                kwargs["VersionIdMarker"] = version_id_marker

            response = client.list_object_versions(**kwargs)
            for item in response.get("Versions", ()):
                size = int(item.get("Size", 0))
                if size < 0:
                    return None
                total += size

            if not response.get("IsTruncated"):
                break

            next_key_marker = response.get("NextKeyMarker")
            if not isinstance(next_key_marker, str) or not next_key_marker:
                return None
            key_marker = next_key_marker

            next_version_marker = response.get("NextVersionIdMarker")
            version_id_marker = (
                next_version_marker
                if isinstance(next_version_marker, str) and next_version_marker
                else None
            )
    except Exception:
        return None

    return total


def _measure_qdrant_points(client, collection: str) -> int | None:
    try:
        info = client.get_collection(collection)
        value = getattr(info, "points_count", None)
    except Exception:
        return None
    if value is None:
        return None
    count = int(value)
    return count if count >= 0 else None


def measure_cloud_usage(
    session: Session,
    *,
    s3_client,
    qdrant_client,
    s3_bucket: str,
    qdrant_collection: str,
) -> CloudUsage:
    """Read current usage from the three required persistence services.

    The operation is read-only: PostgreSQL database size, all B2 object-version
    metadata, and Qdrant collection point count. Failures are represented as
    unknown (`None`) so capacity policy can fail closed rather than guessing.
    """
    return CloudUsage(
        supabase_bytes=_measure_database_bytes(session),
        backblaze_b2_bytes=_measure_b2_bytes(s3_client, s3_bucket),
        qdrant_points=_measure_qdrant_points(qdrant_client, qdrant_collection),
    )


def assess_measured_capacity(
    usage: CloudUsage,
    limits: CloudBudgetLimits,
) -> tuple[tuple[ServiceCapacity, ...], CapacityDecision]:
    """Apply explicit ceilings to measured usage and return fail-closed capacity."""
    services = (
        assess_usage_budget(
            "supabase",
            used=usage.supabase_bytes,
            limit=(limits.supabase_max_mb * _MIB if limits.supabase_max_mb is not None else None),
            low_watermark_percent=limits.low_watermark_percent,
        ),
        assess_usage_budget(
            "backblaze_b2",
            used=usage.backblaze_b2_bytes,
            limit=(limits.backblaze_b2_max_mb * _MIB if limits.backblaze_b2_max_mb is not None else None),
            low_watermark_percent=limits.low_watermark_percent,
        ),
        assess_usage_budget(
            "qdrant",
            used=usage.qdrant_points,
            limit=limits.qdrant_max_points,
            low_watermark_percent=limits.low_watermark_percent,
        ),
    )
    return services, evaluate_capacity(services)
