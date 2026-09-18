from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from app.api.dashboard import require_dashboard_auth
from app.services.conflict_investigation import build_conflict_investigation_snapshot
from app.services.document_detail import build_document_detail
from app.services.evidence_quality_scorecards import build_evidence_quality_scorecards
from app.services.evidence_search import build_evidence_search_snapshot
from app.services.intelligence import build_intelligence_snapshot
from app.services.provenance_graph import build_provenance_graph
from app.services.timeline import build_timeline_snapshot

API_VERSION = "v1"

router = APIRouter(
    prefix="/api/v1",
    tags=["read-only-v1"],
    dependencies=[Depends(require_dashboard_auth)],
)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("")
def api_v1_meta(response: Response) -> dict[str, object]:
    _no_store(response)
    return {
        "api_version": API_VERSION,
        "mode": "protected_read_only_evidence_api",
        "endpoints": {
            "intelligence": "/api/v1/intelligence",
            "evidence_search": "/api/v1/evidence/search",
            "document_detail": "/api/v1/documents/{document_id}",
            "timeline": "/api/v1/timeline",
            "conflicts": "/api/v1/conflicts",
            "provenance": "/api/v1/provenance/{document_id}",
            "quality_scorecards": "/api/v1/quality/scorecards",
        },
        "safety": {
            "authenticated": True,
            "read_only": True,
            "write_routes": False,
            "ingestion_controls": False,
            "trust_controls": False,
            "raw_object_keys_exposed": False,
            "forecasting": False,
            "trading_actions": False,
        },
    }


@router.get("/intelligence")
def api_v1_intelligence(
    response: Response,
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, object]:
    _no_store(response)
    return build_intelligence_snapshot(source_id=source_id, limit=limit)


@router.get("/evidence/search")
def api_v1_evidence_search(
    response: Response,
    q: str | None = Query(default=None, max_length=500),
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    state: str | None = Query(default=None, min_length=2, max_length=32),
    entity: str | None = Query(default=None, max_length=255),
    metric: str | None = Query(default=None, max_length=255),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=5000),
) -> dict[str, object]:
    _no_store(response)
    try:
        return build_evidence_search_snapshot(
            q=q,
            source_id=source_id,
            state=state,
            entity=entity,
            metric=metric,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/documents/{document_id}")
def api_v1_document_detail(
    response: Response,
    document_id: str = Path(min_length=1, max_length=128),
) -> dict[str, object]:
    _no_store(response)
    result = build_document_detail(document_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return result


@router.get("/timeline")
def api_v1_timeline(
    response: Response,
    entity: str | None = Query(default=None, min_length=1, max_length=255),
    metric: str | None = Query(default=None, min_length=1, max_length=255),
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    series_limit: int = Query(default=20, ge=1, le=50),
    points_per_series: int = Query(default=30, ge=1, le=100),
) -> dict[str, object]:
    _no_store(response)
    return build_timeline_snapshot(
        entity=entity,
        metric=metric,
        source_id=source_id,
        series_limit=series_limit,
        points_per_series=points_per_series,
    )


@router.get("/conflicts")
def api_v1_conflicts(
    response: Response,
    participant_source_id: str | None = Query(default=None, min_length=2, max_length=64),
    entity_contains: str | None = Query(default=None, max_length=255),
    metric_contains: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    _no_store(response)
    try:
        return build_conflict_investigation_snapshot(
            participant_source_id=participant_source_id,
            entity_contains=entity_contains,
            metric_contains=metric_contains,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/provenance/{document_id}")
def api_v1_provenance(
    response: Response,
    document_id: str = Path(min_length=1, max_length=128),
) -> dict[str, object]:
    _no_store(response)
    result = build_provenance_graph(document_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return result


@router.get("/quality/scorecards")
def api_v1_quality_scorecards(response: Response) -> dict[str, object]:
    _no_store(response)
    try:
        return build_evidence_quality_scorecards()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
