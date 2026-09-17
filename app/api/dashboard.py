from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import get_settings
from app.dashboard import build_dashboard_snapshot
from app.services.intelligence import build_intelligence_snapshot

router = APIRouter()
security = HTTPBasic(auto_error=False)


def require_dashboard_auth(
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> None:
    settings = get_settings()
    username = settings.dashboard_username
    password = settings.dashboard_password

    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard authentication is not configured.",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Basic"},
        )

    valid_user = secrets.compare_digest(credentials.username.encode(), username.encode())
    valid_password = secrets.compare_digest(credentials.password.encode(), password.encode())
    if not (valid_user and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dashboard credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )


DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Financial Intelligence Dashboard</title>
  <style>
    :root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1180px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center}.badge{padding:8px 12px;border-radius:999px;font-weight:700}.healthy{background:#dcfce7;color:#166534}.warning{background:#fef3c7;color:#92400e}.blocked{background:#fee2e2;color:#991b1b}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:18px 0}.card{background:white;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d}.muted{color:#6b7280;font-size:13px}.value{font-size:26px;font-weight:800;margin-top:4px}.row{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid #eef2f7}.row:last-child{border-bottom:0}button{border:0;background:#111827;color:white;border-radius:10px;padding:10px 14px;cursor:pointer}table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}th,td{text-align:left;padding:11px 12px;border-bottom:1px solid #eef2f7;font-size:14px}th{background:#f9fafb}.ok{color:#166534;font-weight:700}.bad{color:#991b1b;font-weight:700}@media(max-width:700px){.top{align-items:flex-start;flex-direction:column}table{display:block;overflow-x:auto}}
  </style>
</head>
<body><main class="wrap">
  <div class="top"><div><h1>Financial Intelligence Agent</h1><div class="muted">Private read-only operational dashboard</div></div><div><span id="overall" class="badge">Loading…</span> <button onclick="loadStatus()">Refresh</button></div></div>
  <div class="grid">
    <div class="card"><div class="muted">Documents</div><div id="documents" class="value">-</div></div>
    <div class="card"><div class="muted">Claims</div><div id="claims" class="value">-</div></div>
    <div class="card"><div class="muted">Qdrant points</div><div id="qdrant" class="value">-</div></div>
    <div class="card"><div class="muted">Pending queue</div><div id="pending" class="value">-</div></div>
    <div class="card"><div class="muted">Trust events</div><div id="trust" class="value">-</div></div>
    <div class="card"><div class="muted">Capacity</div><div id="capacity" class="value">-</div></div>
  </div>
  <div class="card"><h2>Source monitors</h2><div id="monitors"></div></div>
  <h2>Recent monitor runs</h2><table><thead><tr><th>Source</th><th>Outcome</th><th>Started</th><th>Discovered</th><th>Ingested</th><th>Error</th></tr></thead><tbody id="runs"></tbody></table>
  <p class="muted">Protected intelligence JSON: <code>/dashboard/intelligence</code>. It organizes persisted evidence only and does not generate trading signals.</p>
  <p id="updated" class="muted"></p><p id="note" class="muted"></p>
</main>
<script>
function esc(v){return String(v ?? '-').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function fmtTime(v){if(!v)return '-';return new Date(v).toLocaleString();}
async function loadStatus(){
  const badge=document.getElementById('overall'); badge.textContent='Loading…'; badge.className='badge';
  try{
    const r=await fetch('/dashboard/status',{cache:'no-store'}); if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    badge.textContent=d.overall_status.toUpperCase(); badge.className='badge '+d.overall_status;
    documents.textContent=d.totals.documents; claims.textContent=d.totals.claims;
    qdrant.textContent=`${d.totals.actual_qdrant_points ?? '?'} / ${d.totals.expected_qdrant_points}`;
    pending.textContent=d.queue.pending; trust.textContent=d.totals.trust_events;
    capacity.textContent=d.capacity.safe?'SAFE':'BLOCKED'; capacity.className='value '+(d.capacity.safe?'ok':'bad');
    monitors.innerHTML=d.monitors.map(m=>`<div class="row"><span><strong>${esc(m.source_id.toUpperCase())}</strong><br><span class="muted">${esc(m.monitor_id)}</span></span><span class="${m.state==='ready'?'ok':'bad'}">${esc(m.state)}<br><span class="muted">${esc(fmtTime(m.last_success_at))}</span></span></div>`).join('');
    runs.innerHTML=d.recent_runs.map(x=>`<tr><td>${esc(x.source_id.toUpperCase())}</td><td>${esc(x.outcome)}</td><td>${esc(fmtTime(x.started_at))}</td><td>${esc(x.discovered_count)}</td><td>${esc(x.ingested_count)}</td><td>${esc(x.error_code)}</td></tr>`).join('');
    updated.textContent='Updated: '+fmtTime(d.generated_at); note.textContent=d.integrity_note;
  }catch(e){badge.textContent='UNAVAILABLE';badge.className='badge blocked';note.textContent='Dashboard status could not be loaded.';}
}
loadStatus(); setInterval(loadStatus,300000);
</script></body></html>'''


@router.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_auth)])
def dashboard_page() -> str:
    return DASHBOARD_HTML


@router.get("/dashboard/status", dependencies=[Depends(require_dashboard_auth)])
def dashboard_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_dashboard_snapshot()


@router.get("/dashboard/intelligence", dependencies=[Depends(require_dashboard_auth)])
def dashboard_intelligence(
    response: Response,
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_intelligence_snapshot(source_id=source_id, limit=limit)
