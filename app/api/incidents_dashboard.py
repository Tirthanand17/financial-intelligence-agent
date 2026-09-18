from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.incidents import build_incident_snapshot

router = APIRouter()


INCIDENTS_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Incident Center</title>
<style>:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1100px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.clear{color:#166534}.attention{color:#92400e}.blocked{color:#991b1b}.incident{border-left:4px solid #d1d5db}.critical{border-left-color:#dc2626}.high{border-left-color:#d97706}.pill{font-size:11px;font-weight:800;text-transform:uppercase;background:#f3f4f6;border-radius:999px;padding:5px 8px}.head{display:flex;justify-content:space-between;gap:12px}.nav,button{display:inline-block;background:#111827;color:#fff;border:0;border-radius:9px;padding:10px 13px;text-decoration:none;cursor:pointer}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px;margin:14px 0}@media(max-width:700px){.top,.head{flex-direction:column}}</style></head>
<body><main class="wrap"><div class="top"><div><h1>Incident Center</h1><p class="muted">Deterministic read-only operator alerts derived from the current readiness snapshot.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <button onclick="loadData()">Refresh</button></div></div>
<div class="grid"><div class="card"><div class="muted">Status</div><div id="status" class="metric">-</div></div><div class="card"><div class="muted">Incidents</div><div id="total" class="metric">-</div></div><div class="card"><div class="muted">Critical</div><div id="critical" class="metric blocked">-</div></div><div class="card"><div class="muted">High</div><div id="high" class="metric attention">-</div></div></div>
<div id="safety" class="banner">Loading…</div><div id="items"></div><p id="updated" class="muted"></p>
<script>function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}function incident(x){return `<div class="card incident ${esc(x.severity)}"><div class="head"><div><strong>${esc(x.title)}</strong><div class="muted">${esc(x.code)}${x.source_id?' · '+esc(x.source_id).toUpperCase():''}</div></div><span class="pill">${esc(x.severity)}</span></div><p>${esc(x.detail)}</p><pre class="muted" style="white-space:pre-wrap">${esc(JSON.stringify(x.evidence,null,2))}</pre></div>`}async function loadData(){const r=await fetch('/dashboard/incidents/status',{cache:'no-store'});if(!r.ok){safety.textContent='Incident snapshot unavailable: HTTP '+r.status;return}const d=await r.json();status.textContent=d.status.toUpperCase();status.className='metric '+d.status;total.textContent=d.summary.incidents;critical.textContent=d.summary.critical;high.textContent=d.summary.high;safety.textContent=d.safety.note+(d.summary.notification_delivery_configured?'':' External notification delivery is not configured.');items.innerHTML=d.incidents.length?d.incidents.map(incident).join(''):'<div class="card clear"><strong>No deterministic incidents detected by the current readiness rules.</strong></div>';updated.textContent='Updated: '+new Date(d.generated_at).toLocaleString()}loadData();</script></main></body></html>'''


@router.get(
    "/dashboard/incidents",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def incidents_page() -> str:
    return INCIDENTS_HTML


@router.get(
    "/dashboard/incidents/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def incidents_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_incident_snapshot()


@router.get(
    "/api/v1/incidents",
    dependencies=[Depends(require_dashboard_auth)],
)
def api_v1_incidents(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_incident_snapshot()
