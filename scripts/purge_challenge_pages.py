import argparse

from qdrant_client import models
from sqlalchemy import select

from app.core.config import get_settings
from app.ingestion.quality import STRONG_BLOCK_MARKERS, WEAK_BLOCK_MARKERS
from app.storage.database import DocumentRecord, get_session
from app.storage.object_store import delete_raw_document
from app.storage.vector_store import get_qdrant_client


def _looks_like_challenge(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if any(marker in normalized for marker in STRONG_BLOCK_MARKERS):
        return True
    return sum(marker in normalized for marker in WEAK_BLOCK_MARKERS) >= 2


def _load_points() -> list[object]:
    settings = get_settings()
    client = get_qdrant_client()
    points: list[object] = []
    offset = None

    while True:
        batch, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points.extend(batch)
        if offset is None:
            break

    return points


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or remove anti-bot/challenge pages accidentally indexed as trusted evidence."
    )
    parser.add_argument("--apply", action="store_true", help="Actually delete the identified records.")
    args = parser.parse_args()

    settings = get_settings()
    client = get_qdrant_client()
    points = _load_points()

    bad_document_ids: set[str] = set()
    for point in points:
        payload = dict(getattr(point, "payload", None) or {})
        if payload.get("source_id") != "rbi":
            continue
        if _looks_like_challenge(str(payload.get("text", ""))):
            document_id = str(payload.get("document_id", ""))
            if document_id:
                bad_document_ids.add(document_id)

    bad_point_ids = [
        str(getattr(point, "id"))
        for point in points
        if str((getattr(point, "payload", None) or {}).get("document_id", "")) in bad_document_ids
    ]

    print(f"Challenge documents found: {len(bad_document_ids)}")
    print(f"Qdrant points affected: {len(bad_point_ids)}")

    if not bad_document_ids:
        print("Nothing to clean.")
        return

    if not args.apply:
        print("Preview only. Re-run with --apply to delete these rejected challenge-page records.")
        return

    if bad_point_ids:
        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=models.PointIdsList(points=bad_point_ids),
            wait=True,
        )

    with get_session() as session:
        records = list(
            session.scalars(
                select(DocumentRecord).where(DocumentRecord.id.in_(bad_document_ids))
            )
        )
        for record in records:
            delete_raw_document(record.object_key)
            session.delete(record)
        session.commit()

    print(f"Deleted {len(bad_document_ids)} challenge documents from Qdrant, object storage, and PostgreSQL.")


if __name__ == "__main__":
    main()
