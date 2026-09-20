from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

import httpx

from app.core.config import get_settings
from app.monitoring.measurements import (
    CloudBudgetLimits,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.services.world_bank_persistence import persist_world_bank_payload
from app.sources.registry import validate_source_url
from app.sources.world_bank import (
    WORLD_BANK_INDICATOR_SPECS,
    build_world_bank_indicator_url,
    parse_world_bank_indicator_payload,
)
from app.storage.database import get_session
from app.storage.object_store import get_s3_client
from app.storage.vector_store import get_qdrant_client


WORLD_BANK_LIVE_CANARY_CONFIRMATION = "WORLD_BANK_LIVE_CANARY"
_WORLD_BANK_MAX_RESPONSE_BYTES = 1024 * 1024
_WORLD_BANK_JSON_CONTENT_TYPES = frozenset({"application/json", "text/json"})


@dataclass(frozen=True, slots=True)
class WorldBankLiveDownload:
    source_url: str
    final_url: str
    content: bytes
    content_type: str
    sha256: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class WorldBankLiveCanaryResult:
    status: str
    indicator_code: str
    sha256: str
    document_id: str
    chunk_count: int
    claim_count: int
    observation_periods: tuple[str, ...]
    source_last_updated: str | None
    live_canary_performed: bool = True


def _require_safe_runtime() -> None:
    settings = get_settings()
    if settings.trust_promotion_enabled:
        raise RuntimeError("WORLD_BANK_CANARY_BLOCKED_TRUST_PROMOTION_ENABLED")
    if settings.source_monitoring_enabled or settings.source_auto_ingest_enabled:
        raise RuntimeError("WORLD_BANK_CANARY_BLOCKED_OPERATIONAL_GATES_ENABLED")


def _require_capacity() -> None:
    settings = get_settings()
    limits = CloudBudgetLimits(
        supabase_max_mb=settings.monitor_supabase_max_mb,
        backblaze_b2_max_mb=settings.monitor_b2_max_mb,
        qdrant_max_points=settings.monitor_qdrant_max_points,
        low_watermark_percent=settings.monitor_capacity_low_watermark_percent,
    )
    with get_session() as session:
        usage = measure_cloud_usage(
            session,
            s3_client=get_s3_client(),
            qdrant_client=get_qdrant_client(),
            s3_bucket=settings.s3_bucket,
            qdrant_collection=settings.qdrant_collection,
        )
    _, decision = assess_measured_capacity(usage, limits)
    if not decision.allow_ingestion:
        blockers = ",".join(decision.blocking_services) or "unknown"
        raise RuntimeError(f"WORLD_BANK_CANARY_CAPACITY_BLOCKED:{decision.reason}:{blockers}")


def download_world_bank_live_payload(
    indicator_code: str,
    *,
    recent_observations: int = 3,
) -> WorldBankLiveDownload:
    """Fetch exactly one bounded World Bank Indicators API payload.

    Redirects are rejected rather than followed. The response is capped at 1 MiB,
    must be JSON, must remain on the already allow-listed World Bank host, and is
    parsed before it can be returned for persistence.
    """
    source_url = build_world_bank_indicator_url(
        indicator_code,
        recent_observations=recent_observations,
    )
    validate_source_url("world_bank", source_url)

    headers = {
        "User-Agent": "FinancialIntelligenceAgent/0.3 (+bounded-world-bank-canary)",
        "Accept": "application/json",
    }
    with httpx.Client(follow_redirects=False, timeout=30.0, headers=headers) as client:
        with client.stream("GET", source_url) as response:
            if 300 <= response.status_code < 400:
                raise ValueError("World Bank live canary rejects redirects")
            response.raise_for_status()

            final_url = str(response.url)
            validate_source_url("world_bank", final_url)
            if final_url != source_url:
                raise ValueError("World Bank live canary final URL changed unexpectedly")

            declared_length = response.headers.get("content-length")
            if declared_length and declared_length.isdigit():
                if int(declared_length) > _WORLD_BANK_MAX_RESPONSE_BYTES:
                    raise ValueError("World Bank live canary response exceeds 1 MiB")

            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in _WORLD_BANK_JSON_CONTENT_TYPES:
                raise ValueError("World Bank live canary returned a non-JSON content type")

            buffer = bytearray()
            for block in response.iter_bytes(chunk_size=64 * 1024):
                buffer.extend(block)
                if len(buffer) > _WORLD_BANK_MAX_RESPONSE_BYTES:
                    raise ValueError("World Bank live canary response exceeds 1 MiB")
            content = bytes(buffer)

    if not content:
        raise ValueError("World Bank live canary returned an empty response")

    # Validate exact accepted bytes before any persistence write occurs.
    parse_world_bank_indicator_payload(
        content,
        expected_indicator_code=indicator_code,
        max_observations=recent_observations,
    )
    return WorldBankLiveDownload(
        source_url=source_url,
        final_url=final_url,
        content=content,
        content_type=content_type,
        sha256=sha256(content).hexdigest(),
        retrieved_at=datetime.now(UTC),
    )


def run_world_bank_live_canary(
    *,
    indicator_code: str,
    recent_observations: int = 3,
    allow_network: bool = False,
    allow_write: bool = False,
    confirmation: str = "",
) -> WorldBankLiveCanaryResult:
    """Run one explicitly approved network+write canary with full reconciliation.

    This function is intentionally not referenced by the recurring scheduler or
    monitoring registry. It remains a manual canary until a separate activation
    decision is made after rollout closeout and review of the live evidence.
    """
    if indicator_code not in WORLD_BANK_INDICATOR_SPECS:
        raise ValueError("Unsupported World Bank indicator code")
    if not allow_network or not allow_write:
        raise RuntimeError("WORLD_BANK_CANARY_REQUIRES_EXPLICIT_NETWORK_AND_WRITE_FLAGS")
    if confirmation != WORLD_BANK_LIVE_CANARY_CONFIRMATION:
        raise RuntimeError("WORLD_BANK_CANARY_CONFIRMATION_REQUIRED")

    _require_safe_runtime()
    _require_capacity()
    downloaded = download_world_bank_live_payload(
        indicator_code,
        recent_observations=recent_observations,
    )
    persisted = persist_world_bank_payload(
        content=downloaded.content,
        indicator_code=indicator_code,
        source_url=downloaded.source_url,
        final_url=downloaded.final_url,
        recent_observations=recent_observations,
        retrieved_at=downloaded.retrieved_at,
        expected_sha256=downloaded.sha256,
    )
    if persisted.claim_count != 0:
        raise RuntimeError("WORLD_BANK_CANARY_UNEXPECTED_CLAIM_CREATION")

    # Re-measure after the one-item write. If the safety ceiling is crossed, the
    # canary fails closed; the already-preserved evidence is never deleted.
    _require_capacity()
    return WorldBankLiveCanaryResult(
        status=persisted.status,
        indicator_code=indicator_code,
        sha256=persisted.sha256,
        document_id=persisted.document_id,
        chunk_count=persisted.chunk_count,
        claim_count=persisted.claim_count,
        observation_periods=persisted.observation_periods,
        source_last_updated=persisted.source_last_updated,
    )
