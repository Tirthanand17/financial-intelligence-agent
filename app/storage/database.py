from datetime import date, datetime, timezone
from functools import lru_cache
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, Integer, Numeric, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class DocumentRecord(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(128))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_key: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chunk_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="indexed")


class ClaimRecord(Base):
    """Persisted, source-grounded financial claim.

    Claim state is stored as text so state transitions can be handled explicitly
    by the verification/trust layers instead of being coupled to a database enum.
    """

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    document_id: Mapped[str] = mapped_column(String(36), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str] = mapped_column(Text)

    entity: Mapped[str] = mapped_column(String(255), index=True)
    metric: Mapped[str] = mapped_column(String(255), index=True)
    value_text: Mapped[str] = mapped_column(Text)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(30, 10), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)

    publication_date = mapped_column(Date, nullable=True, index=True)
    effective_date = mapped_column(Date, nullable=True, index=True)

    evidence_text: Mapped[str] = mapped_column(Text)
    evidence_chunk_index: Mapped[int] = mapped_column(Integer)

    confidence: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(32), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ClaimEntityAttributionRecord(Base):
    """Auditable provenance for the canonical subject assigned to a claim.

    This stays separate from `claims` so Phase 3 can be deployed without an
    in-place migration of the existing claim table. One claim has at most one
    recorded extraction-time attribution decision. Claims created before entity
    attribution can be backfilled idempotently from preserved source evidence.
    """

    __tablename__ = "claim_entity_attributions"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canonical_entity: Mapped[str] = mapped_column(String(255), index=True)
    source_default_entity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    basis: Mapped[str] = mapped_column(String(64), index=True)
    matched_aliases: Mapped[str] = mapped_column(Text)
    ambiguous_candidates: Mapped[str] = mapped_column(Text)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ClaimSupersessionRecord(Base):
    """Audit trail linking an older claim to the newer claim that replaced it.

    This is a separate table so version history can be added to an existing
    deployment without altering the already-created `claims` table. The older
    claim remains in place and only its state changes to `superseded`.
    """

    __tablename__ = "claim_supersessions"

    older_claim_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    newer_claim_id: Mapped[str] = mapped_column(String(36), index=True)
    newer_document_id: Mapped[str] = mapped_column(String(36), index=True)
    temporal_kind: Mapped[str] = mapped_column(String(32))
    older_date: Mapped[date] = mapped_column(Date)
    newer_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ClaimVerificationEventRecord(Base):
    """Audit trail for automatic verification/conflict state transitions.

    Events are append-only. The current state remains on `claims`, while this
    table preserves why an automatic transition occurred and which independent
    source IDs supported or conflicted with the claim at that time.
    """

    __tablename__ = "claim_verification_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    from_state: Mapped[str] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(128))
    supporting_source_ids: Mapped[str] = mapped_column(Text)
    conflicting_source_ids: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ClaimTrustEventRecord(Base):
    """Append-only audit event for VERIFIED -> TRUSTED promotion.

    The current state remains on `claims`. This table records exactly why a
    conservative trust promotion happened and which independent authoritative
    source IDs qualified as corroboration at that moment.
    """

    __tablename__ = "claim_trust_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    from_state: Mapped[str] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(128))
    corroborating_source_ids: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SourceMonitorStateRecord(Base):
    """Current operational state for one explicit source monitor.

    This table contains only non-secret operational metadata. It never stores
    credentials, request headers, or raw exception messages.
    """

    __tablename__ = "source_monitor_states"

    monitor_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(128))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_document_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SourceMonitorRunRecord(Base):
    """Append-only, secret-free observability event for one monitor attempt."""

    __tablename__ = "source_monitor_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    monitor_id: Mapped[str] = mapped_column(String(128), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(128))
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    ingested_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    blocking_services: Mapped[str] = mapped_column(Text, default="[]")
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    return _session_factory()()


def find_document_by_sha(session: Session, sha256: str) -> DocumentRecord | None:
    return session.scalar(select(DocumentRecord).where(DocumentRecord.sha256 == sha256))
