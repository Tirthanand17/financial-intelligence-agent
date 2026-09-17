from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.corroboration import build_corroboration_snapshot

router = APIRouter()


CORROBORATION_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Corroboration Diagnostics</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block;margin:2px}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.item{border-left:4px solid #d1d5db}.conflict{border-left-color:#dc2626}.support{border-left-color:#16a34a}.temporal{border-left-color:#d97706}.coverage{border-left-color:#2563eb}.pill{font-size:11px;font-weight:800;background:#f3f4f6;border-radius:999px;padding:5px 8px}.head{display:flex;justify-content:space-between;gap:14px}.evidence{background:#f9fafb;padding:10px;border-radius:9px;font-size:13px;line-height:1.5;margin-top:8px}button,select{padding:10px;border-radius:9px}button{border:0;background:#111827;color:#fff;cursor:pointer}select{border:1px solid #d1d5db;background:#fff}.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{background:#eef2ff;padding:6px 9px;border-radius:999px;font-size:12px}@media(max-width:720px){.top,.head{flex-direction:column}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Corroboration Diagnostics</h1><p class="muted">Read-only explanation of independent-source coverage for candidate claims. No verification or trust state is changed here.</p></div><div><a class="nav" href="/dashboard/hub">Hub</a><a class="nav" href="/dashboard/verification">Verification</a><a class="nav" href="/dashboard/timeline">Timeline</a></div></div>
<div class="card"><label>Items <select id="limit"><option>25</option><option selected>100</option><option>200</option><option>300</option></select></label> <button onclick="loadData()">Refresh</button> <span id="updated" class="muted"></span></div>
<div class="grid"><div class="card"><div class="muted">Total claims</div><div id="total" class="metric">-</div></div><div class="card"><div class="muted">Quality-safe nonterminal</div><div id="safe" class="metric">-</div></div><div class="card"><div class="muted">Candidates</div><div id="candidates" class="metric">-</div></div><div class="card"><div class="muted">Returned diagnostics</div><div id="returned" class="metric">-</div></div></div>
<h2>Diagnostic distribution</h2><div id="reasons" class="chips"></div><h2>Candidate review</h2><div id="items"></div><p id="note" class="muted"></p>
<script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function klass(v){return v==='qualifying_independent_conflict_exists'?'conflict':v==='qualifying_independent_support_exists'?'support':v==='temporal_alignment_missing'?'temporal':'coverage';}
function peers(v){return (v||[]).map(x=>`${esc(x.source_id.toUpperCase())} (${esc(x.temporal_scope?x.temporal_scope.kind+':'+x.temporal_scope.date:'undated')})`).join(', ')||'none';}
function card(x){return `<div class="card item ${klass(x.diagnostic_reason)}"><div class="head"><div><strong>${esc(x.entity)}</strong><div class="muted">${esc(x.metric)} · ${esc(x.source_id).toUpperCase()} · ${esc(x.value_text)} ${esc(x.unit||'')}</div></div><span class="pill">${esc(x.diagnostic_reason)}</span></div><div class="muted">Target scope: ${esc(x.temporal_scope?x.temporal_scope.kind+':'+x.temporal_scope.date:'undated')} · Independent peers: ${esc(x.independent_peer_count)}</div><div class="muted">Exact support: ${peers(x.exact_support)}<br>Exact conflicts: ${peers(x.exact_conflicts)}<br>Same value / missing scope: ${peers(x.same_value_missing_scope)}<br>Same value / different scope: ${peers(x.same_value_different_scope)}</div><div class="evidence">${esc(x.evidence_excerpt)}</div></div>`;}
async function loadData(){try{const limit=document.getElementById('limit').value;const r=await fetch('/dashboard/corroboration/status?limit='+encodeURIComponent(limit),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();total.textContent=d.summary.total_claims;safe.textContent=d.summary.quality_safe_nonterminal_claims;candidates.textContent=d.summary.candidate_claims;returned.textContent=d.summary.diagnostics_returned;updated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();reasons.innerHTML=Object.entries(d.reason_counts).map(([k,v])=>`<span class="chip">${esc(k)}: ${esc(v)}</span>`).join('');items.innerHTML=d.items.map(card).join('')||'<div class="card muted">No candidate diagnostics.</div>';note.textContent=d.safety.note;}catch(e){note.textContent='Corroboration diagnostics could not be loaded.';}}
loadData();
</script></main></body></html>'''


@router.get(
    "/dashboard/corroboration",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def corroboration_page() -> str:
    return CORROBORATION_HTML


@router.get(
    "/dashboard/corroboration/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def corroboration_status(
    response: Response,
    limit: int = Query(default=100, ge=1, le=300),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_corroboration_snapshot(limit=limit)
