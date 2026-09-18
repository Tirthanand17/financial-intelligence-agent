from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.evidence_export import build_claim_export, render_claim_export_csv

api_router = APIRouter(
    prefix="/api/v1/export",
    tags=["read-only-v1-export"],
    dependencies=[Depends(require_dashboard_auth)],
)

dashboard_router = APIRouter()


def _build_export(
    *,
    q: str | None,
    source_id: str | None,
    state: str | None,
    entity: str | None,
    metric: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> dict[str, object]:
    try:
        return build_claim_export(
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


@api_router.get("/claims.json")
def export_claims_json(
    response: Response,
    q: str | None = Query(default=None, max_length=500),
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    state: str | None = Query(default=None, min_length=2, max_length=32),
    entity: str | None = Query(default=None, max_length=255),
    metric: str | None = Query(default=None, max_length=255),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=5000),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = 'attachment; filename="financial-intelligence-claims.json"'
    return _build_export(
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


@api_router.get("/claims.csv")
def export_claims_csv(
    q: str | None = Query(default=None, max_length=500),
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    state: str | None = Query(default=None, min_length=2, max_length=32),
    entity: str | None = Query(default=None, max_length=255),
    metric: str | None = Query(default=None, max_length=255),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=5000),
) -> Response:
    payload = _build_export(
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
    return Response(
        content=render_claim_export_csv(payload),
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="financial-intelligence-claims.csv"',
        },
    )


EXPORT_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Evidence Export</title>
<style>:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:980px;margin:auto;padding:28px}.card{background:#fff;border-radius:14px;padding:18px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.field{display:flex;flex-direction:column;gap:5px}.field input,.field select{padding:10px;border:1px solid #d1d5db;border-radius:9px}.muted{color:#6b7280;font-size:13px;line-height:1.45}.btn,.nav{display:inline-block;border:0;background:#111827;color:#fff;border-radius:10px;padding:10px 14px;text-decoration:none;cursor:pointer;margin-right:8px}.notice{background:#eff6ff;color:#1e3a8a;border-radius:10px;padding:12px 14px;margin-top:14px}</style></head>
<body><main class="wrap"><h1>Evidence Export</h1><p class="muted">Bounded exports of already-persisted structured claim evidence. Private storage object keys are never included.</p>
<div class="card"><div class="grid">
<div class="field"><label>Text</label><input id="q" maxlength="500"></div>
<div class="field"><label>Source</label><input id="source" maxlength="64" placeholder="rbi"></div>
<div class="field"><label>State</label><input id="state" maxlength="32" placeholder="candidate"></div>
<div class="field"><label>Entity</label><input id="entity" maxlength="255"></div>
<div class="field"><label>Metric</label><input id="metric" maxlength="255"></div>
<div class="field"><label>Date from</label><input id="dateFrom" type="date"></div>
<div class="field"><label>Date to</label><input id="dateTo" type="date"></div>
<div class="field"><label>Rows</label><select id="limit"><option>25</option><option>50</option><option selected>100</option></select></div>
</div><p><a id="json" class="btn" href="#">Export JSON</a><a id="csv" class="btn" href="#">Export CSV</a><a class="nav" href="/dashboard/hub">Workspace</a></p>
<div class="notice">Exports are read-only and limited to 100 rows per request. Use filters or the API offset parameter for larger inspected datasets. Dates use persisted effective date, otherwise publication date; missing dates remain missing.</div></div>
<script>function params(){const p=new URLSearchParams();[['q','q'],['source_id','source'],['state','state'],['entity','entity'],['metric','metric'],['date_from','dateFrom'],['date_to','dateTo'],['limit','limit']].forEach(([k,id])=>{const v=document.getElementById(id).value.trim();if(v)p.set(k,v)});return p.toString()}function update(){const s=params();document.getElementById('json').href='/api/v1/export/claims.json'+(s?'?'+s:'');document.getElementById('csv').href='/api/v1/export/claims.csv'+(s?'?'+s:'')}document.querySelectorAll('input,select').forEach(x=>x.addEventListener('input',update));update();</script>
</main></body></html>'''


@dashboard_router.get(
    "/dashboard/export",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def evidence_export_page() -> str:
    return EXPORT_HTML
