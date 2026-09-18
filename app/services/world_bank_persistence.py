from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlparse
from uuid import uuid4

from app.sources.registry import get_source, validate_source_url
from app.sources.world_bank import (
    WORLD_BANK_INDICATOR_SPECS,
    WorldBankObservation,
    build_world_bank_indicator_url,
    parse_world_bank_indicator_payload,
)
from app.storage.database import DocumentRecord, find_document_by_sha, get_session
from app.storage.object_store import get_raw_document, put_raw_document
from app.storage.vector_store import count_indexed_document_points, index_chunks


WORLD_BANK_CONTENT_TYPE = "application/json"
RECONCILIATION_REQUIRED = "reconciliation_required"
INDEXED = "indexed"


@dataclass(frozen=True, slots=True)
class WorldBankPersistenceResult:
    document_id: str
    status: str
    sha256: str
    object_key: str
    chunk_count: int
    claim_count: int
    source_last_updated: str | None
    observation_periods: tuple[str, ...]
    live_canary_performed: bool = False


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    return value.astimezone(UTC)


def _validate_bounded_url(
    url: str,
    *,
    indicator_code: str,
    recent_observations: int,
) -> None:
    """Require the exact bounded World Bank query contract, ignoring query order."""
    validate_source_url("world_bank", url)
    expected = urlparse(
        build_world_bank_indicator_url(
            indicator_code,
            recent_observations=recent_observations,
        )
    )
    actual = urlparse(url)
    if (
        actual.scheme.lower(),
        (actual.hostname or "").lower(),
        actual.path.rstrip("/"),
    ) != (
        expected.scheme.lower(),
        (expected.hostname or "").lower(),
        expected.path.rstrip("/"),
    ):
        raise ValueError("World Bank URL is outside the bounded candidate contract")
    if sorted(parse_qsl(actual.query, keep_blank_values=True)) != sorted(
        parse_qsl(expected.query, keep_blank_values=True)
    ):
        raise ValueError("World Bank URL query is outside the bounded candidate contract")


def _decimal_text(value: object) -> str:
    return "missing" if value is None else format(value, "f")


def _observation_chunk(
    observation: WorldBankObservation,
    *,
    source_last_updated: str | None,
) -> str:
    """Render deterministic vector evidence without converting periods into claim dates."""
    status = observation.observation_status or "observed"
    source_unit = observation.source_unit or "not supplied"
    eligibility = "yes" if observation.eligible_for_fact else "no"
    return "\n".join(
        (
            "World Bank Indicators API evidence",
            f"Country: {observation.country_name} ({observation.country_code})",
            f"Indicator code: {observation.indicator_code}",
            f"Indicator name: {observation.indicator_name}",
            f"Canonical metric: {observation.canonical_metric}",
            (
                "Observation period: "
                f"{observation.observation_period} (annual observation period; not a publication/effective date)"
            ),
            f"Value: {_decimal_text(observation.value_numeric)}",
            f"Source unit: {source_unit}",
            f"Expected normalized unit: {observation.expected_unit}",
            f"Observation status: {status}",
            f"Eligible for future structured-fact mapping: {eligibility}",
            (
                "Source last updated: "
                f"{source_last_updated or 'unknown'} (source metadata; not a claim publication/effective date)"
            ),
            "Claim publication date: unknown",
            "Claim effective date: unknown",
        )
    )


def _verify_preserved_bytes(*, object_key: str, expected_sha256: str) -> None:
    replayed = get_raw_document(object_key)
    replayed_sha = sha256(replayed).hexdigest()
    if replayed_sha != expected_sha256:
        raise RuntimeError("WORLD_BANK_RAW_EVIDENCE_HASH_MISMATCH")


def persist_world_bank_payload(
    *,
    content: bytes,
    indicator_code: str,
    source_url: str,
    final_url: str,
    recent_observations: int,
    retrieved_at: datetime,
    expected_sha256: str | None = None,
) -> WorldBankPersistenceResult:
    """Persist already-acquired bounded World Bank bytes with fail-closed reconciliation.

    This function performs no network fetch and is not wired to a live monitor or
    scheduler. It intentionally creates no structured claims because a World Bank
    annual observation period is not equivalent to this project's publication or
    effective date semantics. A separate reviewed temporal model is required before
    observations can become claims.
    """
    if indicator_code not in WORLD_BANK_INDICATOR_SPECS:
        raise ValueError("Unsupported World Bank indicator code")
    if not 1 <= recent_observations <= 5:
        raise ValueError("recent_observations must be between 1 and 5")
    retrieved_at_utc = _utc(retrieved_at)

    _validate_bounded_url(
        source_url,
        indicator_code=indicator_code,
        recent_observations=recent_observations,
    )
    _validate_bounded_url(
        final_url,
        indicator_code=indicator_code,
        recent_observations=recent_observations,
    )

    digest = sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Accepted World Bank bytes do not match expected SHA-256")

    parsed = parse_world_bank_indicator_payload(
        content,
        expected_indicator_code=indicator_code,
        max_observations=recent_observations,
    )
    if parsed.raw_content != content:
        raise RuntimeError("WORLD_BANK_ADAPTER_CHANGED_ACCEPTED_BYTES")
    if not parsed.observations:
        raise ValueError("World Bank payload contains no observations")

    source_last_updated = (
        parsed.source_last_updated.isoformat()
        if parsed.source_last_updated is not None
        else None
    )
    chunks = [
        _observation_chunk(item, source_last_updated=source_last_updated)
        for item in parsed.observations
    ]
    source = get_source("world_bank")
    title = (
        "World Bank Indicators API — India — "
        f"{WORLD_BANK_INDICATOR_SPECS[indicator_code].canonical_metric}"
    )

    with get_session() as session:
        existing = find_document_by_sha(session, digest)
        if existing is not None:
            if existing.source_id != "world_bank":
                raise RuntimeError("WORLD_BANK_HASH_OWNED_BY_DIFFERENT_SOURCE")
            _verify_preserved_bytes(
                object_key=existing.object_key,
                expected_sha256=digest,
            )
            indexed_points = count_indexed_document_points(
                document_id=existing.id,
                chunk_count=existing.chunk_count,
            )
            if existing.status == INDEXED and indexed_points == existing.chunk_count:
                return WorldBankPersistenceResult(
                    document_id=existing.id,
                    status="already_indexed",
                    sha256=digest,
                    object_key=existing.object_key,
                    chunk_count=existing.chunk_count,
                    claim_count=0,
                    source_last_updated=source_last_updated,
                    observation_periods=tuple(
                        item.observation_period for item in parsed.observations
                    ),
                )
            document = existing
            document.status = RECONCILIATION_REQUIRED
            document.chunk_count = len(chunks)
            session.commit()
        else:
            document_id = str(uuid4())
            object_key = put_raw_document(
                source_id="world_bank",
                sha256=digest,
                content=content,
                content_type=WORLD_BANK_CONTENT_TYPE,
            )
            _verify_preserved_bytes(object_key=object_key, expected_sha256=digest)
            document = DocumentRecord(
                id=document_id,
                source_id="world_bank",
                source_name=source.name,
                source_url=source_url,
                final_url=final_url,
                title=title,
                content_type=WORLD_BANK_CONTENT_TYPE,
                sha256=digest,
                object_key=object_key,
                retrieved_at=retrieved_at_utc,
                chunk_count=len(chunks),
                status=RECONCILIATION_REQUIRED,
            )
            session.add(document)
            session.commit()

        index_chunks(
            document_id=document.id,
            chunks=chunks,
            payload_base={
                "source_id": "world_bank",
                "source_name": source.name,
                "source_url": source_url,
                "final_url": final_url,
                "content_type": WORLD_BANK_CONTENT_TYPE,
                "sha256": digest,
                "indicator_code": indicator_code,
                "temporal_semantics": "annual_observation_period_not_claim_date",
            },
        )
        indexed_points = count_indexed_document_points(
            document_id=document.id,
            chunk_count=len(chunks),
        )
        if indexed_points != len(chunks):
            raise RuntimeError("WORLD_BANK_QDRANT_RECONCILIATION_MISMATCH")

        document.status = INDEXED
        document.chunk_count = len(chunks)
        session.commit()

        return WorldBankPersistenceResult(
            document_id=document.id,
            status=INDEXED,
            sha256=digest,
            object_key=document.object_key,
            chunk_count=len(chunks),
            claim_count=0,
            source_last_updated=source_last_updated,
            observation_periods=tuple(
                item.observation_period for item in parsed.observations
            ),
        )
