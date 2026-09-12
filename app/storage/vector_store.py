from functools import lru_cache
from uuid import NAMESPACE_URL, uuid5

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

from app.core.config import get_settings


@lru_cache
def get_embedder() -> TextEmbedding:
    settings = get_settings()
    return TextEmbedding(model_name=settings.embedding_model)


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return [vector.tolist() for vector in get_embedder().embed(texts)]


def _ensure_collection(vector_size: int) -> None:
    settings = get_settings()
    client = get_qdrant_client()
    if client.collection_exists(settings.qdrant_collection):
        return
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
    )


def index_chunks(*, document_id: str, chunks: list[str], payload_base: dict[str, object]) -> None:
    if not chunks:
        raise ValueError("Cannot index an empty chunk list")

    settings = get_settings()
    vectors = embed_texts(chunks)
    _ensure_collection(len(vectors[0]))

    points: list[models.PointStruct] = []
    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        point_id = str(uuid5(NAMESPACE_URL, f"{document_id}:{index}"))
        payload = dict(payload_base)
        payload.update({"document_id": document_id, "chunk_index": index, "text": chunk})
        points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

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

    query_vector = embed_texts([question])[0]
    query_filter = None
    if source_id:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="source_id", match=models.MatchValue(value=source_id))]
        )

    result = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
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
