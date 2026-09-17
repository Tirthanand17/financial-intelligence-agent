from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.timeline import build_timeline_snapshot

router = APIRouter()


TIMELINE_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Evidence Timeline Explorer</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1320px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.field{display:flex;flex-direction:column;gap:5px}.field label{font-size:12px;color:#6b7280}.field select{padding:10px;border:1px solid #d1d5db;border-radius:9px;background:#fff;min-width:190px;max-width:320px}button{border:0;background:#111827;color:#fff;border-radius:10px;padding:11px 15px;cursor:pointer}.series-title{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.latest{font-size:18px;font-weight:800}.pill{font-size:11px;font-weight:800;text-transform:uppercase;background:#eef2ff;border-radius:999px;padding:5px 8px}.warn{color:#92400e}.bad{color:#991b1b}.ok{color:#166534}table{width:100%;border-collapse:collapse;margin-top:12px}th,td{text-align:left;padding:9px;border-bottom:1px solid #eef2f7;font-size:13px;vertical-align:top}th{background:#f9fafb}.evidence{max-width:420px;line-height:1.4}.source{word-break:break-word}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px}.error{background:#fee2e2;color:#991b1b}@media(max-width:760px){.top,.series-title{flex-direction:column}.toolbar{align-items:stretch}.field select{width:100%;max-width:none}table{display:block;overflow-x:auto}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Evidence Timeline Explorer</h1><p class="muted">Chronological structured evidence using only persisted publication/effective dates. Undated evidence stays undated.</p></div><div><a class="nav" href="/dashboard">Dashboard</a> <a class="nav" href="/dashboard/intelligence-view">Intelligence</a> <a class="nav" href="/dashboard/verification">Verification</a></div></div>
<div class="card toolbar"><div class="field"><label>Entity</label><select id="entity"><option value="">All entities</option></select></div><div class="field"><label>Metric</label><select id="metric"><option value="">All metrics</option></select></div><div class="field"><label>Source</label><select id="source"><option value="">All sources</option></select></div><div class="field"><label>Series</label><select id="seriesLimit"><option>10</option><option selected>20</option><option>30</option><option>50</option></select></div><div class="field"><label>Points / series</label><select id="pointsLimit"><option>10</option><option selected>30</option><option>50</option><option>100</option></select></div><button onclick="loadData()">Apply / Refresh</button><span id="updated" class="muted"></span></div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">Claims in scope</div><div id="claims" class="metric">-</div></div><div class="card"><div class="muted">Series in scope</div><div id="seriesCount" class="metric">-</div></div><div class="card"><div class="muted">Quality-safe claims</div><div id="quality" class="metric ok">-</div></div><div class="card"><div class="muted">Conflicted claims</div><div id="conflicted" class="metric bad">-</div></div><div class="card"><div class="muted">Undated claims</div><div id="undated" class="metric warn">-</div></div></div>
<div id="safety" class="banner"></div><h2>Evidence series</h2><div id="series"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function fmtTime(v){if(!v)return '-';return new Date(v).toLocaleString();}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function populate(id,values,labelFn){const el=document.getElementById(id),current=el.value,known=new Set(Array.from(el.options).map(o=>o.value));values.forEach(v=>{const value=typeof v==='string'?v:v.source_id;if(!known.has(value)){const o=document.createElement('option');o.value=value;o.textContent=labelFn(v);el.appendChild(o);known.add(value);}});el.value=current;}
function pointRow(p){const u=safeUrl(p.source_url);const link=u?`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">source</a>`:'-';const date=p.temporal_date?`${esc(p.temporal_date)}<br><span class="muted">${esc(p.temporal_basis)}</span>`:'<span class="warn">undated</span>';const history=p.superseded_by_claim_id?`superseded by ${esc(p.superseded_by_claim_id)}`:(p.supersedes_claim_ids||[]).length?`supersedes ${(p.supersedes_claim_ids||[]).map(esc).join(', ')}`:'-';return `<tr><td>${date}</td><td><strong>${esc(p.value_text)}</strong> ${esc(p.unit||'')}<br><span class="muted">${esc(p.state)} · confidence ${esc(p.confidence)}</span></td><td>${esc(p.source_id).toUpperCase()}<br>${link}</td><td>${esc(p.quality_gate)}${p.quality_rejection_reason?'<br><span class="warn">'+esc(p.quality_rejection_reason)+'</span>':''}</td><td>${esc(history)}</td><td class="evidence">${esc(p.evidence_excerpt)}</td></tr>`;}
function seriesCard(s){const latest=s.latest_active?`${esc(s.latest_active.value_text)} · ${esc(s.latest_active.source_id).toUpperCase()} · ${esc(s.latest_active.state)}`:'No active claim';return `<section class="card"><div class="series-title"><div><h3>${esc(s.entity)} — ${esc(s.metric)}</h3><div class="muted">Unit ${esc(s.unit)} · ${esc(s.point_count)} total points · ${esc(s.quality_safe_points)} quality-safe · ${esc(s.conflicted_points)} conflicts · ${esc(s.undated_points)} undated</div></div><div><div class="muted">Latest active evidence</div><div class="latest">${latest}</div><div class="muted">Latest dated scope: ${esc(s.latest_temporal_date)}</div></div></div><table><thead><tr><th>Date</th><th>Value / state</th><th>Source</th><th>Quality</th><th>History</th><th>Evidence</th></tr></thead><tbody>${s.points.map(pointRow).join('')}</tbody></table></section>`;}
async function loadData(){const err=document.getElementById('err');err.style.display='none';try{const q=new URLSearchParams({series_limit:seriesLimit.value,points_per_series:pointsLimit.value});if(entity.value)q.set('entity',entity.value);if(metric.value)q.set('metric',metric.value);if(source.value)q.set('source_id',source.value);const r=await fetch('/dashboard/timeline/status?'+q.toString(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();claims.textContent=d.summary.claims_in_scope;seriesCount.textContent=d.summary.series_in_scope;quality.textContent=d.summary.quality_safe_claims;conflicted.textContent=d.summary.conflicted_claims;undated.textContent=d.summary.undated_claims;safety.textContent=d.safety.note;updated.textContent='Updated: '+fmtTime(d.generated_at);populate('entity',d.facets.entities,x=>x);populate('metric',d.facets.metrics,x=>x);populate('source',d.facets.sources,x=>`${x.source_id.toUpperCase()} · ${x.source_name}`);series.innerHTML=d.series.map(seriesCard).join('')||'<div class="card muted">No timeline series match this scope.</div>';}catch(e){err.textContent='Timeline could not be loaded: '+e.message;err.style.display='block';}}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/timeline",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def timeline_page() -> str:
    return TIMELINE_HTML


@router.get(
    "/dashboard/timeline/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def timeline_status(
    response: Response,
    entity: str | None = Query(default=None, min_length=1, max_length=255),
    metric: str | None = Query(default=None, min_length=1, max_length=255),
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    series_limit: int = Query(default=20, ge=1, le=50),
    points_per_series: int = Query(default=30, ge=1, le=100),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_timeline_snapshot(
        entity=entity,
        metric=metric,
        source_id=source_id,
        series_limit=series_limit,
        points_per_series=points_per_series,
    )
