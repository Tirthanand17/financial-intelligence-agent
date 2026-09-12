from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, Integer, String, Text, create_engine, select
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
