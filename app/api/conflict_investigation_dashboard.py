from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.conflict_investigation import build_conflict_investigation_snapshot

router = APIRouter()


CONFLICT_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Conflict Investigation</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1280px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav,button{display:inline-block;background:#111827;color:#fff;border:0;padding:10px 14px;border-radius:10px;text-decoration:none;cursor:pointer}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.toolbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;align-items:end}.field{display:flex;flex-direction:column;gap:5px}.field label,.muted{color:#6b7280;font-size:13px}.field input,.field select{padding:10px;border:1px solid #d1d5db;border-radius:9px;background:#fff;width:100%;box-sizing:border-box}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:12px}.metric{font-size:26px;font-weight:800}.conflict{border-left:4px solid #dc2626}.head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.pill{font-size:11px;font-weight:800;text-transform:uppercase;padding:5px 8px;border-radius:999px;background:#fee2e2;color:#991b1b}.values{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:12px}.valuebox{background:#f9fafb;border-radius:10px;padding:12px}.value{font-size:19px;font-weight:800}.claim{border-top:1px solid #e5e7eb;padding-top:9px;margin-top:9px}.evidence{margin-top:6px;font-size:13px;line-height:1.45}.source{font-size:12px;word-break:break-all}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px;margin:12px 0}.error{background:#fee2e2;color:#991b1b}@media(max-width:720px){.top,.head{flex-direction:column}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Conflict Investigation</h1><p class="muted">Read-only comparison of independently published persisted claims that disagree in the same exact entity, metric, unit, and temporal scope.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/quality-coverage">Coverage</a></div></div>
<div class="card toolbar">
  <div class="field"><label>Participant source ID</label><input id="source" maxlength="64" placeholder="rbi"></div>
  <div class="field"><label>Entity contains</label><input id="entity" maxlength="255" placeholder="Reserve Bank"></div>
  <div class="field"><label>Metric contains</label><input id="metric" maxlength="255" placeholder="Repo Rate"></div>
  <div class="field"><label>Max conflict groups</label><select id="limit"><option>20</option><option selected>50</option><option>100</option></select></div>
  <button onclick="loadData()">Investigate</button>
</div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">Active claims scanned</div><div id="scanned" class="metric">-</div></div><div class="card"><div class="muted">Comparison groups</div><div id="groups" class="metric">-</div></div><div class="card"><div class="muted">Independent conflicts</div><div id="conflictsCount" class="metric">-</div></div><div class="card"><div class="muted">Independent agreements</div><div id="agreements" class="metric">-</div></div><div class="card"><div class="muted">Missing-date excluded</div><div id="missing" class="metric">-</div></div></div>
<div id="contract" class="banner"></div><div id="items"></div><div id="safety" class="banner"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function claimHtml(c){const u=safeUrl(c.source_url);const doc=c.document;return `<div class="claim"><strong>${esc(c.source_name)} (${esc(c.source_id).toUpperCase()})</strong> · Authority ${esc(c.authority_level)} · publisher group ${esc(c.independence_group)}<div class="muted">state ${esc(c.state)} · confidence ${esc(c.confidence)} · publication ${esc(c.publication_date)} · effective ${esc(c.effective_date)}</div><div class="evidence">${esc(c.evidence_excerpt)}</div>${doc?`<div class="muted">Document: ${esc(doc.title||c.document_id)} · SHA-256 ${esc(doc.sha256)} · ${esc(doc.status)}</div>`:''}${u?`<a class="source" href="${esc(u)}" target="_blank" rel="noopener noreferrer">Open source evidence</a>`:''}</div>`;}
function valueHtml(v){return `<div class="valuebox"><div class="value">${esc(v.display_value)} ${esc(v.unit||'')}</div><div class="muted">sources ${esc((v.source_ids||[]).join(', '))} · independent publishers ${esc((v.independence_groups||[]).join(', '))}</div>${(v.claims||[]).map(claimHtml).join('')}</div>`;}
function groupHtml(x){return `<section class="card conflict"><div class="head"><div><h2>${esc(x.entity)} — ${esc(x.canonical_metric)}</h2><div class="muted">Original metric: ${esc(x.source_metric)} · indicator ${esc(x.indicator_id||'unmapped exact metric')} · unit ${esc(x.unit)} · ${esc(x.temporal_kind)} ${esc(x.temporal_date)}</div></div><span class="pill">${esc(x.distinct_values)} VALUES</span></div><p>${esc(x.interpretation)}</p><div class="values">${(x.values||[]).map(valueHtml).join('')}</div></section>`;}
function setIf(params,key,id){const v=document.getElementById(id).value.trim();if(v)params.set(key,v);}
async function loadData(){const err=document.getElementById('err');err.style.display='none';try{const p=new URLSearchParams({limit:document.getElementById('limit').value});setIf(p,'participant_source_id','source');setIf(p,'entity_contains','entity');setIf(p,'metric_contains','metric');const r=await fetch('/dashboard/conflicts/status?'+p.toString(),{cache:'no-store'});if(!r.ok){let msg='HTTP '+r.status;try{const j=await r.json();msg=j.detail||msg;}catch(e){}throw new Error(msg);}const d=await r.json();scanned.textContent=d.summary.active_claims_scanned;groups.textContent=d.summary.comparison_groups_in_scope;conflictsCount.textContent=d.summary.independent_conflict_groups;agreements.textContent=d.summary.independent_agreement_groups;missing.textContent=d.summary.missing_temporal_scope_excluded;contract.textContent=`Comparison: ${d.comparison_contract.entity} entity + ${d.comparison_contract.metric} + exact unit + persisted temporal scope. Publisher independence is enforced.`;items.innerHTML=d.conflicts.map(groupHtml).join('')||'<div class="card muted">No independently published conflicting values were found in this scope.</div>';safety.textContent=d.safety.note;}catch(e){err.textContent='Conflict investigation could not be loaded: '+e.message;err.style.display='block';}}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/conflicts",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def conflict_investigation_page() -> str:
    return CONFLICT_HTML


@router.get(
    "/dashboard/conflicts/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def conflict_investigation_status(
    response: Response,
    participant_source_id: str | None = Query(default=None, min_length=2, max_length=64),
    entity_contains: str | None = Query(default=None, max_length=255),
    metric_contains: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_conflict_investigation_snapshot(
        participant_source_id=participant_source_id,
        entity_contains=entity_contains,
        metric_contains=metric_contains,
        limit=limit,
    )
