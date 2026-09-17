from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.evidence_search import build_evidence_search_snapshot

router = APIRouter()


EVIDENCE_SEARCH_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Evidence Search</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1280px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{display:inline-block;background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none}.toolbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;align-items:end}.field{display:flex;flex-direction:column;gap:5px}.field label{font-size:12px;color:#6b7280}.field input,.field select{padding:10px;border:1px solid #d1d5db;border-radius:9px;background:#fff;width:100%;box-sizing:border-box}button{border:0;background:#111827;color:#fff;border-radius:10px;padding:11px 15px;cursor:pointer}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.claim{border-left:4px solid #2563eb}.doc{border-left:4px solid #7c3aed}.head{display:flex;justify-content:space-between;gap:14px}.pill{font-size:11px;font-weight:800;text-transform:uppercase;padding:5px 8px;border-radius:999px;background:#eef2ff}.value{font-size:19px;font-weight:750;margin:8px 0}.evidence{background:#f9fafb;border-radius:9px;padding:10px;font-size:13px;line-height:1.5;margin-top:8px}.meta{font-size:12px;color:#6b7280;line-height:1.5}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px;margin:12px 0}.error{background:#fee2e2;color:#991b1b}.source{word-break:break-all;font-size:12px}.section{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:24px}@media(max-width:720px){.top,.head,.section{flex-direction:column;align-items:flex-start}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Evidence Search</h1><p class="muted">Search already-persisted claims and document provenance. Read-only, bounded, literal matching only.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/intelligence-view">Intelligence</a></div></div>
<div class="card toolbar">
  <div class="field"><label>Text</label><input id="q" maxlength="200" placeholder="repo rate, inflation, circular..."></div>
  <div class="field"><label>Source ID</label><input id="source" maxlength="64" placeholder="rbi"></div>
  <div class="field"><label>Claim state</label><input id="state" maxlength="32" placeholder="candidate"></div>
  <div class="field"><label>Entity contains</label><input id="entity" maxlength="255" placeholder="Reserve Bank"></div>
  <div class="field"><label>Metric contains</label><input id="metric" maxlength="255" placeholder="Policy Repo Rate"></div>
  <div class="field"><label>Date from</label><input id="dateFrom" type="date"></div>
  <div class="field"><label>Date to</label><input id="dateTo" type="date"></div>
  <div class="field"><label>Page size</label><select id="limit"><option>10</option><option selected>25</option><option>50</option><option>100</option></select></div>
  <button onclick="runSearch()">Search</button>
</div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">Claim hits</div><div id="claimHits" class="metric">-</div></div><div class="card"><div class="muted">Document hits</div><div id="documentHits" class="metric">-</div></div><div class="card"><div class="muted">Returned claims</div><div id="returnedClaims" class="metric">-</div></div><div class="card"><div class="muted">Returned documents</div><div id="returnedDocuments" class="metric">-</div></div></div>
<div id="contract" class="banner"></div>
<div class="section"><h2>Claim evidence</h2><span id="updated" class="muted"></span></div><div id="claims"></div>
<div class="section"><h2>Direct document matches</h2><span class="muted">Text/source filters only; claim-only filters do not alter document metadata.</span></div><div id="documents"></div>
<div id="safety" class="banner"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function claimHtml(x){const u=safeUrl(x.source_url);const d=x.document;return `<section class="card claim"><div class="head"><div><strong>${esc(x.entity)}</strong><div>${esc(x.metric)}</div><div class="meta">Canonical: ${esc(x.canonical_metric)} · ${esc(x.indicator_id||'unmapped exact source metric')}</div></div><span class="pill">${esc(x.state)}</span></div><div class="value">${esc(x.value_text)} ${esc(x.unit||'')}</div><div class="meta">Source: ${esc(x.source_id).toUpperCase()} · Temporal: ${esc(x.temporal_date)} (${esc(x.temporal_basis)}) · Quality: ${esc(x.quality_gate)} · Confidence: ${esc(x.confidence)}</div><div class="evidence">${esc(x.evidence_excerpt)}</div>${d?`<div class="meta" style="margin-top:8px">Document: ${esc(d.title||x.document_id)} · SHA-256 ${esc(d.sha256)} · chunks ${esc(d.chunk_count)} · retrieved ${esc(d.retrieved_at)}</div>`:''}${u?`<div style="margin-top:8px"><a class="source" href="${esc(u)}" target="_blank" rel="noopener noreferrer">Open source evidence</a></div>`:''}</section>`;}
function docHtml(x){const u=safeUrl(x.final_url)||safeUrl(x.source_url);return `<section class="card doc"><div class="head"><div><strong>${esc(x.title||x.document_id)}</strong><div class="meta">${esc(x.source_name)} (${esc(x.source_id).toUpperCase()})</div></div><span class="pill">${esc(x.status)}</span></div><div class="meta">SHA-256: ${esc(x.sha256)} · ${esc(x.content_type)} · chunks ${esc(x.chunk_count)} · retrieved ${esc(x.retrieved_at)}</div>${u?`<div style="margin-top:8px"><a class="source" href="${esc(u)}" target="_blank" rel="noopener noreferrer">Open source</a></div>`:''}</section>`;}
function setIf(q,k,id){const v=document.getElementById(id).value.trim();if(v)q.set(k,v);}
async function runSearch(){const err=document.getElementById('err');err.style.display='none';try{const q=new URLSearchParams({limit:document.getElementById('limit').value,offset:'0'});setIf(q,'q','q');setIf(q,'source_id','source');setIf(q,'state','state');setIf(q,'entity','entity');setIf(q,'metric','metric');setIf(q,'date_from','dateFrom');setIf(q,'date_to','dateTo');const r=await fetch('/dashboard/search/status?'+q.toString(),{cache:'no-store'});if(!r.ok){let detail='HTTP '+r.status;try{const body=await r.json();detail=body.detail||detail;}catch(e){}throw new Error(detail);}const d=await r.json();claimHits.textContent=d.summary.claim_hits;documentHits.textContent=d.summary.document_hits;returnedClaims.textContent=d.summary.returned_claims;returnedDocuments.textContent=d.summary.returned_documents;updated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();contract.textContent=d.search_contract.note;claims.innerHTML=d.claims.map(claimHtml).join('')||'<div class="card muted">No claim evidence matched this scope.</div>';documents.innerHTML=d.documents.map(docHtml).join('')||'<div class="card muted">No direct document metadata matched the text/source scope.</div>';safety.textContent=d.safety.note;}catch(e){err.textContent='Evidence search could not be loaded: '+e.message;err.style.display='block';}}
runSearch();
</script></body></html>'''


@router.get(
    "/dashboard/search",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def evidence_search_page() -> str:
    return EVIDENCE_SEARCH_HTML


@router.get(
    "/dashboard/search/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def evidence_search_status(
    response: Response,
    q: str | None = Query(default=None, max_length=200),
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    state: str | None = Query(default=None, min_length=2, max_length=32),
    entity: str | None = Query(default=None, max_length=255),
    metric: str | None = Query(default=None, max_length=255),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=5000),
) -> dict[str, object]:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be on or before date_to",
        )
    response.headers["Cache-Control"] = "no-store"
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
