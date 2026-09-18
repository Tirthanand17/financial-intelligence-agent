from functools import lru_cache
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.core.config import get_settings


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        cloud_inference=True,
    )


def _ensure_filter_indexes() -> None:
    """Ensure payload indexes required by Qdrant Cloud strict-mode filters."""
    settings = get_settings()
    client = get_qdrant_client()
    collection = client.get_collection(settings.qdrant_collection)
    payload_schema = collection.payload_schema or {}

    if "source_id" not in payload_schema:
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="source_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )


def _ensure_collection() -> None:
    settings = get_settings()
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={
                settings.qdrant_vector_name: models.VectorParams(
                    size=settings.qdrant_vector_size,
                    distance=models.Distance.COSINE,
                )
            },
        )

    _ensure_filter_indexes()


def document_point_ids(document_id: str, chunk_count: int) -> list[str]:
    """Return the deterministic point IDs used for one persisted document."""
    if chunk_count < 0:
        raise ValueError("chunk_count cannot be negative")
    return [
        str(uuid5(NAMESPACE_URL, f"{document_id}:{index}"))
        for index in range(chunk_count)
    ]


def count_indexed_document_points(*, document_id: str, chunk_count: int) -> int:
    """Count expected deterministic points without creating or mutating a collection."""
    if chunk_count <= 0:
        return 0

    settings = get_settings()
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        return 0

    records = client.retrieve(
        collection_name=settings.qdrant_collection,
        ids=document_point_ids(document_id, chunk_count),
        with_payload=False,
        with_vectors=False,
    )
    return len(records)


def index_chunks(*, document_id: str, chunks: list[str], payload_base: dict[str, object]) -> None:
    if not chunks:
        raise ValueError("Cannot index an empty chunk list")

    settings = get_settings()
    _ensure_collection()

    points: list[models.PointStruct] = []
    for index, (point_id, chunk) in enumerate(
        zip(document_point_ids(document_id, len(chunks)), chunks, strict=True)
    ):
        payload = dict(payload_base)
        payload.update({"document_id": document_id, "chunk_index": index, "text": chunk})
        points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    settings.qdrant_vector_name: models.Document(
                        text=chunk,
                        model=settings.qdrant_embedding_model,
                    )
                },
                payload=payload,
            )
        )

    get_qdrant_client().upsert(
        collection_name=settings.qdrant_collection,
        points=points,
        wait=True,
    )


def search_chunks(question: str, *, limit: int = 5, source_id: str | None = None) -> list[dict[str, object]]:
    settings = get_settings()
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        return []

    # Existing collections created before the index was added also need to be
    # repaired before a strict-mode filtered query is attempted.
    _ensure_filter_indexes()

    query_filter = None
    if source_id:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="source_id", match=models.MatchValue(value=source_id))]
        )

    result = client.query_points(
        collection_name=settings.qdrant_collection,
        query=models.Document(
            text=question,
            model=settings.qdrant_embedding_model,
        ),
        using=settings.qdrant_vector_name,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )

    matches: list[dict[str, object]] = []
    for point in result.points:
        payload = dict(point.payload or {})
        payload["score"] = float(point.score)
        matches.append(payload)
    return matches
