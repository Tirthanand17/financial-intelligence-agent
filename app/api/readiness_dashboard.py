from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.readiness import build_readiness_snapshot

router = APIRouter()


READINESS_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Operational Readiness</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block;margin:2px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:16px 0}.card{background:white;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:14px}.metric{font-size:25px;font-weight:800}.muted{color:#6b7280;font-size:13px}.ok{color:#166534}.warn{color:#92400e}.bad{color:#991b1b}.badge{padding:7px 10px;border-radius:999px;font-weight:800;text-transform:uppercase}.healthy{background:#dcfce7;color:#166534}.warning{background:#fef3c7;color:#92400e}.blocked{background:#fee2e2;color:#991b1b}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #eef2f7;font-size:13px;vertical-align:top}th{background:#f9fafb}.row{display:flex;justify-content:space-between;gap:18px;padding:9px 0;border-bottom:1px solid #eef2f7}.row:last-child{border-bottom:0}button{border:0;background:#111827;color:#fff;border-radius:10px;padding:10px 14px;cursor:pointer}@media(max-width:760px){.top{flex-direction:column}table{display:block;overflow-x:auto}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Operational Readiness</h1><p class="muted">Read-only health and safety summary for the production evidence system.</p></div><div><a class="nav" href="/dashboard">Dashboard</a><a class="nav" href="/dashboard/intelligence-view">Intelligence</a><a class="nav" href="/dashboard/verification">Verification</a><a class="nav" href="/dashboard/timeline">Timeline</a><button onclick="loadData()">Refresh</button></div></div>
<div style="margin:14px 0"><span id="overall" class="badge">Loading...</span> <span id="updated" class="muted"></span></div>
<div class="grid"><div class="card"><div class="muted">Documents</div><div id="documents" class="metric">-</div></div><div class="card"><div class="muted">Claims</div><div id="claims" class="metric">-</div></div><div class="card"><div class="muted">Qdrant points</div><div id="qdrant" class="metric">-</div></div><div class="card"><div class="muted">Pending queue</div><div id="pending" class="metric">-</div></div><div class="card"><div class="muted">Trust events</div><div id="trust" class="metric">-</div></div><div class="card"><div class="muted">Capacity</div><div id="capacity" class="metric">-</div></div></div>
<div class="card"><h2>Safety checks</h2><div id="checks"></div></div>
<div class="card"><h2>Cloud measurements</h2><div id="cloud"></div></div>
<div class="card"><h2>Runtime gates</h2><div id="gates"></div></div>
<h2>Monitor readiness</h2><table><thead><tr><th>Source</th><th>State</th><th>Failures</th><th>Last success</th></tr></thead><tbody id="monitors"></tbody></table>
<h2>Recent monitor runs</h2><table><thead><tr><th>Source</th><th>Outcome</th><th>Started</th><th>Finished</th><th>Error</th></tr></thead><tbody id="runs"></tbody></table>
<p id="note" class="muted"></p></main>
<script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function fmt(v){if(!v)return '-';return new Date(v).toLocaleString();}
function boolRow(k,v){return `<div class="row"><span>${esc(k.replaceAll('_',' '))}</span><strong class="${v?'ok':'bad'}">${v?'PASS':'ATTENTION'}</strong></div>`;}
async function loadData(){try{const r=await fetch('/dashboard/readiness/status',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();overall.textContent=d.overall_status;overall.className='badge '+d.overall_status;updated.textContent='Updated: '+fmt(d.generated_at);documents.textContent=d.totals.documents;claims.textContent=d.totals.claims;qdrant.textContent=`${d.totals.actual_qdrant_points??'?'} / ${d.totals.expected_qdrant_points}`;pending.textContent=d.queue.pending;trust.textContent=d.totals.trust_events;capacity.textContent=d.capacity.safe?'SAFE':'BLOCKED';capacity.className='metric '+(d.capacity.safe?'ok':'bad');checks.innerHTML=Object.entries(d.checks).map(([k,v])=>boolRow(k,v)).join('');cloud.innerHTML=Object.entries(d.cloud_checks).map(([k,v])=>boolRow(k,v)).join('');gates.innerHTML=Object.entries(d.runtime_gates).map(([k,v])=>`<div class="row"><span>${esc(k.replaceAll('_',' '))}</span><strong class="${v?'warn':'ok'}">${esc(v)}</strong></div>`).join('');monitors.innerHTML=d.monitors.map(x=>`<tr><td>${esc(x.source_id.toUpperCase())}</td><td class="${x.state==='ready'?'ok':'bad'}">${esc(x.state)}</td><td>${esc(x.consecutive_failures)}</td><td>${esc(fmt(x.last_success_at))}</td></tr>`).join('');runs.innerHTML=d.recent_runs.map(x=>`<tr><td>${esc(x.source_id.toUpperCase())}</td><td>${esc(x.outcome)}</td><td>${esc(fmt(x.started_at))}</td><td>${esc(fmt(x.finished_at))}</td><td>${esc(x.error_code)}</td></tr>`).join('');note.textContent=d.integrity_note+' '+d.safety.note;}catch(e){overall.textContent='UNAVAILABLE';overall.className='badge blocked';note.textContent='Readiness snapshot could not be loaded.';}}
loadData();setInterval(loadData,300000);
</script></body></html>'''


@router.get(
    "/dashboard/readiness",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def readiness_page() -> str:
    return READINESS_HTML


@router.get(
    "/dashboard/readiness/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def readiness_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_readiness_snapshot()
