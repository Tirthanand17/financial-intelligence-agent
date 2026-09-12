from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.monitoring.discovery import DiscoveredFeedItem
from app.monitoring.models import MonitorDefinition
from app.storage.database import SourceMonitorDiscoveryRecord


@dataclass(frozen=True, slots=True)
class DiscoveryPersistenceResult:
    created_count: int
    existing_count: int


def _discovery_key(monitor: MonitorDefinition, url: str) -> str:
    payload = "\x1f".join((monitor.monitor_id.strip(), url.strip()))
    return sha256(payload.encode("utf-8")).hexdigest()


def record_discovered_items(
    session: Session,
    monitor: MonitorDefinition,
    items: tuple[DiscoveredFeedItem, ...],
    *,
    seen_at: datetime,
    commit: bool = True,
) -> DiscoveryPersistenceResult:
    """Persist a bounded feed discovery result without following item URLs.

    One queue row exists per monitor + URL. Repeated sightings update metadata and
    counters but do not create duplicate work. This function never downloads or
    ingests the discovered URL; it only persists already validated discovery data.
    """
    created_count = 0
    existing_count = 0

    for item in items:
        key = _discovery_key(monitor, item.url)
        record = session.scalar(
            select(SourceMonitorDiscoveryRecord).where(
                SourceMonitorDiscoveryRecord.discovery_key == key
            )
        )

        if record is None:
            record = SourceMonitorDiscoveryRecord(
                id=str(uuid4()),
                discovery_key=key,
                item_fingerprint=item.fingerprint,
                monitor_id=monitor.monitor_id,
                source_id=monitor.source_id,
                url=item.url,
                title=item.title,
                publication_date=item.publication_date,
                status="pending",
                document_id=None,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                seen_count=1,
            )
            session.add(record)
            created_count += 1
            continue

        if record.monitor_id != monitor.monitor_id or record.source_id != monitor.source_id:
            raise ValueError("discovery identity does not match monitor/source")

        record.item_fingerprint = item.fingerprint
        record.url = item.url
        record.title = item.title
        record.publication_date = item.publication_date
        record.last_seen_at = seen_at
        record.seen_count += 1
        existing_count += 1

    if commit:
        session.commit()
    else:
        session.flush()

    return DiscoveryPersistenceResult(
        created_count=created_count,
        existing_count=existing_count,
    )
