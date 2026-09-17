from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.verification_workbench import build_verification_workbench

router = APIRouter()


VERIFICATION_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Claim Verification Workbench</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}.card{background:white;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.warn{color:#92400e}.ok{color:#166534}.bad{color:#991b1b}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.toolbar select{padding:10px;border:1px solid #d1d5db;border-radius:9px}button{border:0;background:#111827;color:white;border-radius:10px;padding:11px 15px;cursor:pointer}.item{border-left:4px solid #d1d5db}.item.conflict{border-left-color:#dc2626}.item.quality{border-left-color:#ea580c}.item.missing{border-left-color:#d97706}.item.support{border-left-color:#2563eb}.item.ready{border-left-color:#16a34a}.head{display:flex;justify-content:space-between;gap:15px}.pill{font-size:11px;font-weight:800;text-transform:uppercase;background:#f3f4f6;border-radius:999px;padding:5px 8px}.value{font-size:19px;font-weight:750;margin:8px 0}.evidence{background:#f9fafb;padding:10px;border-radius:9px;font-size:13px;line-height:1.5;margin-top:8px}.sources{font-size:12px;margin-top:8px}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px}.error{background:#fee2e2;color:#991b1b}.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{background:#eef2ff;padding:6px 9px;border-radius:999px;font-size:12px}@media(max-width:720px){.top,.head{flex-direction:column}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Claim Verification Workbench</h1><p class="muted">Read-only explanation of why claims remain candidate, conflict, fail quality, or have enough independent support.</p></div><div><a class="nav" href="/dashboard">Dashboard</a> <a class="nav" href="/dashboard/intelligence-view">Intelligence</a></div></div>
<div class="card toolbar"><label>Items <select id="limit"><option>20</option><option selected>50</option><option>100</option><option>200</option></select></label><button onclick="loadData()">Refresh</button><span id="generated" class="muted"></span></div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">Total claims</div><div id="total" class="metric">-</div></div><div class="card"><div class="muted">Actionable review</div><div id="actionable" class="metric warn">-</div></div><div class="card"><div class="muted">Ready for verification</div><div id="ready" class="metric ok">-</div></div><div class="card"><div class="muted">Verification events</div><div id="events" class="metric">-</div></div></div>
<div class="banner" id="safety"></div>
<h2>Reason distribution</h2><div id="reasons" class="chips"></div>
<h2>Review queue</h2><div id="items"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function klass(reason){return reason==='independent_sources_disagree'?'conflict':reason==='quality_gate_failed'?'quality':reason==='missing_temporal_scope'?'missing':reason==='insufficient_independent_sources'?'support':reason==='independent_sources_agree'?'ready':'';}
function itemHtml(x){const supp=(x.supporting_source_ids||[]).join(', ')||'none';const conf=(x.conflicting_source_ids||[]).join(', ')||'none';return `<div class="card item ${klass(x.verification_reason)}"><div class="head"><div><strong>${esc(x.entity)}</strong><div class="muted">${esc(x.metric)} · ${esc(x.source_id).toUpperCase()} · Authority ${esc(x.authority_level)}</div></div><span class="pill">${esc(x.verification_reason)}</span></div><div class="value">${esc(x.value_text)} ${esc(x.unit||'')}</div><div class="muted">Current: ${esc(x.current_state)} → Evidence assessment: ${esc(x.recommended_state)} · Quality: ${esc(x.quality_gate)} · Confidence: ${esc(x.confidence)}</div><div class="sources">Supporting sources: <strong>${esc(supp)}</strong> · Conflicting sources: <strong>${esc(conf)}</strong></div><div class="evidence">${esc(x.evidence_excerpt)}</div></div>`;}
async function loadData(){const e=document.getElementById('err');e.style.display='none';try{const limit=document.getElementById('limit').value;const r=await fetch('/dashboard/verification/status?limit='+encodeURIComponent(limit),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();total.textContent=d.summary.total_claims;actionable.textContent=d.summary.actionable_review_items;ready.textContent=d.summary.ready_for_verification;events.textContent=d.summary.verification_events;generated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();safety.textContent=d.safety.note;reasons.innerHTML=Object.entries(d.reason_counts).map(([k,v])=>`<span class="chip">${esc(k)}: ${esc(v)}</span>`).join('');items.innerHTML=d.items.map(itemHtml).join('')||'<div class="card muted">No claims to display.</div>';}catch(err){e.textContent='Verification workbench could not be loaded.';e.style.display='block';}}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/verification",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def verification_page() -> str:
    return VERIFICATION_HTML


@router.get(
    "/dashboard/verification/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def verification_status(
    response: Response,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_verification_workbench(limit=limit)
