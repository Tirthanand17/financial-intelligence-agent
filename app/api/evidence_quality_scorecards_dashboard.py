from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.evidence_quality_scorecards import build_evidence_quality_scorecards

router = APIRouter()


QUALITY_SCORECARDS_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Evidence Quality Scorecards</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1280px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav,button{display:inline-block;background:#111827;color:#fff;border:0;padding:10px 14px;border-radius:10px;text-decoration:none;cursor:pointer}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.dim{display:grid;grid-template-columns:minmax(230px,1fr) 100px 100px 110px;gap:8px;padding:8px 0;border-bottom:1px solid #eef2f7}.dim:last-child{border-bottom:0}.ok{color:#166534;font-weight:700}.warn{color:#92400e;font-weight:700}.source{border-left:4px solid #2563eb}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px;margin:12px 0}.error{background:#fee2e2;color:#991b1b}.missing{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}@media(max-width:720px){.top{flex-direction:column}.dim{grid-template-columns:1fr 70px 70px 80px;font-size:12px}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Evidence Quality Scorecards</h1><p class="muted">Factual completeness and provenance dimensions only. There is no composite truth score, source ranking, or automatic trust decision.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/quality-coverage">Coverage</a></div></div>
<div class="card"><button onclick="loadData()">Refresh</button> <span id="updated" class="muted"></span></div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">Claims</div><div id="claims" class="metric">-</div></div><div class="card"><div class="muted">Active claims</div><div id="active" class="metric">-</div></div><div class="card"><div class="muted">Sources represented</div><div id="sources" class="metric">-</div></div><div class="card"><div class="muted">Issue examples</div><div id="issues" class="metric">-</div></div></div>
<div id="interpretation" class="banner"></div>
<h2>Overall factual dimensions</h2><div id="overall" class="card"></div>
<h2>Per-source dimensions</h2><div id="sourceCards"></div>
<h2>Example gaps</h2><div id="examples"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
const labels={quality_gate_pass:'Quality gate pass',temporal_scope_present:'Temporal scope present',entity_attribution_recorded:'Entity attribution recorded',linked_document_present:'Linked document present',document_sha_present:'Document SHA-256 present',raw_evidence_reference_present:'Raw evidence retained',source_registry_known:'Trusted source registry known',indicator_catalog_mapped:'Indicator exact-alias mapped'};
function dimsHtml(card){return Object.entries(card.dimensions).map(([k,v])=>`<div class="dim"><div><strong>${esc(labels[k]||k)}</strong></div><div class="ok">${esc(v.present)} present</div><div class="${v.missing?'warn':'ok'}">${esc(v.missing)} missing</div><div>${esc(v.percent_present)}%</div></div>`).join('');}
function sourceHtml(card){return `<section class="card source"><h3>${esc(String(card.source_id).toUpperCase())}</h3><div class="muted">${esc(card.claims_total)} total · ${esc(card.claims_active)} active</div>${dimsHtml(card)}</section>`;}
function exampleHtml(x){return `<div class="card"><strong>${esc(x.entity)} — ${esc(x.metric)}</strong><div class="muted">${esc(x.source_id).toUpperCase()} · ${esc(x.state)} · claim ${esc(x.claim_id)}</div><div class="missing">missing: ${esc((x.missing_dimensions||[]).join(', '))}</div></div>`;}
async function loadData(){const err=document.getElementById('err');err.style.display='none';try{const r=await fetch('/dashboard/quality-scorecards/status',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();claims.textContent=d.overall.claims_total;active.textContent=d.overall.claims_active;sources.textContent=d.per_source.length;issues.textContent=d.issue_examples.length;updated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();interpretation.textContent=d.interpretation.note;overall.innerHTML=dimsHtml(d.overall);sourceCards.innerHTML=d.per_source.map(sourceHtml).join('')||'<div class="card muted">No sources.</div>';examples.innerHTML=d.issue_examples.map(exampleHtml).join('')||'<div class="card muted">No missing dimensions found in the bounded snapshot.</div>';}catch(e){err.textContent='Quality scorecards could not be loaded: '+e.message;err.style.display='block';}}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/quality-scorecards",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def quality_scorecards_page() -> str:
    return QUALITY_SCORECARDS_HTML


@router.get(
    "/dashboard/quality-scorecards/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def quality_scorecards_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_evidence_quality_scorecards()
