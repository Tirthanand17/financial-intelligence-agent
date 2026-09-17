from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.change_detection import build_change_detection_snapshot

router = APIRouter()


CHANGE_DETECTION_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Evidence Change Detection</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1260px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{display:inline-block;background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:end}.field{display:flex;flex-direction:column;gap:5px}.field label{font-size:12px;color:#6b7280}.field input,.field select{padding:10px;border:1px solid #d1d5db;border-radius:9px;background:#fff}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.event{border-left:4px solid #2563eb}.increase{border-left-color:#16a34a}.decrease{border-left-color:#dc2626}.supersession{border-left-color:#7c3aed}.head{display:flex;justify-content:space-between;gap:14px}.pill{font-size:11px;font-weight:800;text-transform:uppercase;padding:5px 8px;border-radius:999px;background:#eef2ff}.values{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.box{background:#f9fafb;border-radius:10px;padding:12px}.evidence{font-size:13px;line-height:1.45;margin-top:7px}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px}.error{background:#fee2e2;color:#991b1b}button{border:0;background:#111827;color:#fff;border-radius:10px;padding:11px 15px;cursor:pointer}@media(max-width:720px){.top,.head{flex-direction:column}.values{grid-template-columns:1fr}.toolbar{align-items:stretch}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Evidence Change Detection</h1><p class="muted">Read-only factual differences between comparable persisted dated claims. No forecasts or trading signals.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/timeline">Timeline</a></div></div>
<div class="card toolbar"><div class="field"><label>Source ID (optional)</label><input id="source" placeholder="rbi"></div><div class="field"><label>Entity (optional)</label><input id="entity" placeholder="Reserve Bank of India"></div><div class="field"><label>Max changes</label><select id="limit"><option>25</option><option selected>50</option><option>100</option><option>200</option></select></div><button onclick="loadData()">Apply / Refresh</button><span id="updated" class="muted"></span></div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">Eligible dated claims</div><div id="eligible" class="metric">-</div></div><div class="card"><div class="muted">Series compared</div><div id="series" class="metric">-</div></div><div class="card"><div class="muted">Detected changes</div><div id="changesCount" class="metric">-</div></div><div class="card"><div class="muted">Unchanged confirmations</div><div id="unchanged" class="metric">-</div></div></div>
<div id="safety" class="banner"></div><h2>Detected evidence changes</h2><div id="events"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function eventClass(x){if(x.explicit_supersession)return 'supersession';return x.direction==='increase'?'increase':x.direction==='decrease'?'decrease':'';}
function obs(o){const u=safeUrl(o.source_url);return `<div class="box"><strong>${esc(o.value_text)}</strong><div class="muted">${esc(o.source_id).toUpperCase()} · ${esc(o.temporal_date)} · ${esc(o.state)}</div><div class="evidence">${esc(o.evidence_excerpt)}</div>${u?`<div><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">Open source</a></div>`:''}</div>`;}
function eventHtml(x){const delta=x.numeric_delta!==null?` · delta ${esc(x.numeric_delta)} ${esc(x.unit||'')}`:'';return `<section class="card event ${eventClass(x)}"><div class="head"><div><strong>${esc(x.entity)}</strong><div>${esc(x.canonical_metric)}</div><div class="muted">${esc(x.indicator_id||'exact metric')} · ${esc(x.direction||'non-numeric change')}${delta}</div></div><span class="pill">${esc(x.change_kind)}</span></div><div class="values">${obs(x.previous)}${obs(x.current)}</div></section>`;}
async function loadData(){const err=document.getElementById('err');err.style.display='none';try{const q=new URLSearchParams({limit:document.getElementById('limit').value});const s=document.getElementById('source').value.trim(),e=document.getElementById('entity').value.trim();if(s)q.set('source_id',s);if(e)q.set('entity',e);const r=await fetch('/dashboard/changes/status?'+q.toString(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();eligible.textContent=d.summary.eligible_dated_claims;series.textContent=d.summary.series_compared;changesCount.textContent=d.summary.detected_changes;unchanged.textContent=d.summary.unchanged_confirmations;safety.textContent=d.safety.note;updated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();events.innerHTML=d.changes.map(eventHtml).join('')||'<div class="card muted">No comparable changed values found in this scope.</div>';}catch(e){err.textContent='Change detection could not be loaded: '+e.message;err.style.display='block';}}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/changes",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def change_detection_page() -> str:
    return CHANGE_DETECTION_HTML


@router.get(
    "/dashboard/changes/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def change_detection_status(
    response: Response,
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    entity: str | None = Query(default=None, min_length=1, max_length=255),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_change_detection_snapshot(source_id=source_id, entity=entity, limit=limit)
