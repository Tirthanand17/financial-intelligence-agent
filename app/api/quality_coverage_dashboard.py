from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.quality_coverage import build_quality_coverage_snapshot

router = APIRouter()

QUALITY_COVERAGE_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claim Quality & Verification Coverage</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:14px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.ok{color:#166534}.warn{color:#92400e}.bad{color:#991b1b}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.toolbar select{padding:10px;border:1px solid #d1d5db;border-radius:9px}button{border:0;background:#111827;color:white;border-radius:10px;padding:11px 15px;cursor:pointer}table{width:100%;border-collapse:collapse;background:#fff;border-radius:14px;overflow:hidden}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #eef2f7;font-size:13px}th{background:#f9fafb}.pill{display:inline-block;padding:5px 8px;border-radius:999px;font-size:11px;font-weight:800;background:#f3f4f6}.single{color:#92400e}.supported{color:#166534}.conflict{color:#991b1b}.banner{padding:12px 14px;border-radius:10px;background:#eff6ff;color:#1e3a8a}.error{background:#fee2e2;color:#991b1b}@media(max-width:720px){.top{flex-direction:column}table{display:block;overflow-x:auto}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Claim Quality & Verification Coverage</h1><p class="muted">Read-only diagnostics for parser-quality debt, temporal completeness, publisher independence and exact verification comparison groups.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/verification">Verification</a></div></div>
<div class="card toolbar"><label>Groups <select id="limit"><option>50</option><option selected>100</option><option>200</option><option>500</option></select></label><button onclick="loadData()">Refresh</button><span id="generated" class="muted"></span></div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">All claims</div><div id="total" class="metric">-</div></div><div class="card"><div class="muted">Quality-safe active</div><div id="safe" class="metric ok">-</div></div><div class="card"><div class="muted">Quality failed</div><div id="failed" class="metric warn">-</div></div><div class="card"><div class="muted">Missing temporal scope</div><div id="missing" class="metric warn">-</div></div><div class="card"><div class="muted">Independently supported groups</div><div id="supported" class="metric ok">-</div></div><div class="card"><div class="muted">Independent conflicts</div><div id="conflicts" class="metric bad">-</div></div></div>
<div id="safety" class="banner"></div>
<h2>Per-source quality</h2><table><thead><tr><th>Source</th><th>Total</th><th>Active</th><th>Quality pass</th><th>Quality fail</th><th>Missing time scope</th></tr></thead><tbody id="sources"></tbody></table>
<h2>Verification comparison groups</h2><table><thead><tr><th>Entity</th><th>Metric</th><th>Date</th><th>Sources</th><th>Independent groups</th><th>Values</th><th>Status</th></tr></thead><tbody id="groups"></tbody></table>
<h2>Missing temporal scope</h2><table><thead><tr><th>Source</th><th>Entity</th><th>Metric</th><th>Value</th><th>State</th></tr></thead><tbody id="temporal"></tbody></table>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function statusClass(v){return v==='independently_supported_same_value'?'supported':v==='independent_values_disagree'?'conflict':'single';}
async function loadData(){const e=document.getElementById('err');e.style.display='none';try{const limit=document.getElementById('limit').value;const r=await fetch('/dashboard/quality-coverage/status?limit='+encodeURIComponent(limit),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();total.textContent=d.summary.claims_total;safe.textContent=d.summary.quality_safe_active_claims;failed.textContent=d.summary.quality_failed_claims;missing.textContent=d.summary.missing_temporal_scope;supported.textContent=d.summary.independently_supported_groups;conflicts.textContent=d.summary.independent_conflict_groups;generated.textContent='Updated: '+new Date(d.generated_at).toLocaleString();safety.textContent=d.safety.note;sources.innerHTML=d.per_source.map(x=>`<tr><td>${esc(x.source_id.toUpperCase())}</td><td>${esc(x.claims_total)}</td><td>${esc(x.claims_active)}</td><td>${esc(x.quality_passed)}</td><td>${esc(x.quality_failed)}</td><td>${esc(x.missing_temporal_scope)}</td></tr>`).join('')||'<tr><td colspan="6">No source claims.</td></tr>';groups.innerHTML=d.coverage_groups.map(x=>`<tr><td>${esc(x.entity)}</td><td>${esc(x.metric)} ${esc(x.unit||'')}</td><td>${esc(x.temporal_kind)}: ${esc(x.temporal_date)}</td><td>${esc(x.source_ids.join(', '))}</td><td>${esc(x.independence_groups.join(', '))}</td><td>${esc(x.distinct_values)}</td><td class="${statusClass(x.coverage_status)}"><span class="pill">${esc(x.coverage_status)}</span></td></tr>`).join('')||'<tr><td colspan="7">No comparable dated groups.</td></tr>';temporal.innerHTML=d.missing_temporal_items.map(x=>`<tr><td>${esc(x.source_id.toUpperCase())}</td><td>${esc(x.entity)}</td><td>${esc(x.metric)}</td><td>${esc(x.value_text)} ${esc(x.unit||'')}</td><td>${esc(x.state)}</td></tr>`).join('')||'<tr><td colspan="5">No quality-safe active claims are missing temporal scope.</td></tr>';}catch(err){e.textContent='Quality/coverage diagnostics could not be loaded.';e.style.display='block';}}
loadData();
</script></body></html>'''


@router.get(
    "/dashboard/quality-coverage",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def quality_coverage_page() -> str:
    return QUALITY_COVERAGE_HTML


@router.get(
    "/dashboard/quality-coverage/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def quality_coverage_status(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_quality_coverage_snapshot(limit=limit)
