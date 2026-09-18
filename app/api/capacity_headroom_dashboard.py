from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.capacity_headroom import build_capacity_headroom_snapshot

router = APIRouter()


CAPACITY_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Capacity Headroom Planner</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1120px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}.metric{font-size:24px;font-weight:800}.muted{color:#6b7280;font-size:13px}.ok{color:#166534}.warn{color:#92400e}.bad{color:#991b1b}.row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #eef2f7}.row:last-child{border-bottom:0}.banner{padding:12px 14px;border-radius:10px;background:#eff6ff;color:#1e3a8a}.error{background:#fee2e2;color:#991b1b}button{border:0;background:#111827;color:#fff;border-radius:10px;padding:10px 14px;cursor:pointer}@media(max-width:700px){.top{flex-direction:column}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Capacity Headroom Planner</h1><p class="muted">Measured storage/vector headroom against the project's approved safety ceilings. No quota guessing and no evidence deletion.</p></div><div><button onclick="loadData()">Refresh</button> <a class="nav" href="/dashboard/hub">Workspace</a></div></div>
<div id="err" class="banner error" style="display:none"></div><div id="status" class="banner">Loading…</div><div id="services" class="grid"></div>
<div class="card"><h2>Forecast policy</h2><div id="forecast"></div></div>
<div class="card"><h2>Preservation policy</h2><div id="policy"></div></div><p id="updated" class="muted"></p>
<script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function human(v,unit){if(v===null||v===undefined)return 'unknown';if(unit==='points')return Number(v).toLocaleString()+' points';const n=Number(v);if(n>=1073741824)return (n/1073741824).toFixed(2)+' GiB';if(n>=1048576)return (n/1048576).toFixed(2)+' MiB';if(n>=1024)return (n/1024).toFixed(2)+' KiB';return n.toLocaleString()+' bytes';}
function serviceCard(s){const cls=s.state==='ok'?'ok':(s.state==='low'?'warn':'bad');return `<section class="card"><h2>${esc(s.service)}</h2><div class="metric ${cls}">${esc(s.state).toUpperCase()}</div><div class="row"><span>Used</span><strong>${human(s.used,s.unit)}</strong></div><div class="row"><span>Project ceiling</span><strong>${human(s.ceiling,s.unit)}</strong></div><div class="row"><span>Usage</span><strong>${s.usage_percent===null?'unknown':esc(s.usage_percent)+'%'}</strong></div><div class="row"><span>Remaining to safety pause</span><strong>${human(s.remaining_to_pause_threshold,s.unit)}</strong></div><div class="row"><span>Remaining to ceiling</span><strong>${human(s.remaining_to_ceiling,s.unit)}</strong></div><div class="muted">Low-watermark reserve: ${esc(s.low_watermark_percent)}%</div></section>`;}
async function loadData(){const err=document.getElementById('err');err.style.display='none';try{const r=await fetch('/dashboard/capacity-plan/status',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();status.textContent='Planning status: '+d.planning_status.toUpperCase()+' · capacity decision: '+String(d.capacity_decision.safe?'SAFE':'BLOCKED')+' · '+d.capacity_decision.reason;services.innerHTML=d.services.map(serviceCard).join('');forecast.innerHTML=`<div class="row"><span>Time-based forecast available</span><strong>${d.forecast.available?'YES':'NO'}</strong></div><p class="muted">${esc(d.forecast.note)}</p>`;policy.innerHTML=`<div class="row"><span>Delete evidence to make room</span><strong>NO</strong></div><div class="row"><span>Truncate history to make room</span><strong>NO</strong></div><div class="row"><span>Reduce quality to make room</span><strong>NO</strong></div><div class="row"><span>Threshold action</span><strong>${esc(d.policy.action_when_threshold_reached)}</strong></div>`;updated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();}catch(e){err.textContent='Capacity headroom could not be loaded: '+e.message;err.style.display='block';}}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/capacity-plan",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def capacity_plan_page() -> str:
    return CAPACITY_HTML


@router.get(
    "/dashboard/capacity-plan/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def capacity_plan_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_capacity_headroom_snapshot()
