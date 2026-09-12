from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.services.ingestion import ingest_url
from app.services.qa import answer_question
from app.sources.registry import TRUSTED_SOURCES

router = APIRouter()


class IngestRequest(BaseModel):
    source_id: str = Field(min_length=2, max_length=64)
    url: HttpUrl


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    source_id: str | None = Field(default=None, max_length=64)


@router.get("/sources")
def list_sources() -> list[dict[str, object]]:
    return [
        {
            "source_id": source.source_id,
            "name": source.name,
            "category": source.category,
            "authority_level": source.authority_level.value,
            "base_url": source.base_url,
            "enabled": source.enabled,
        }
        for source in TRUSTED_SOURCES
    ]


@router.post("/ingest")
def ingest(request: IngestRequest) -> dict[str, object]:
    try:
        return ingest_url(request.source_id, str(request.url))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ingestion failed: {type(exc).__name__}") from exc


@router.post("/ask")
def ask(request: AskRequest) -> dict[str, object]:
    try:
        return answer_question(
            request.question,
            top_k=request.top_k,
            source_id=request.source_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Retrieval failed: {type(exc).__name__}") from exc
