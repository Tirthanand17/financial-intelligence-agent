from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.intelligence_digest import build_intelligence_digest

router = APIRouter()


DIGEST_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Financial Intelligence Digest</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1180px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric{font-size:25px;font-weight:800}.muted{color:#6b7280;font-size:13px}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.field{display:flex;flex-direction:column;gap:5px}.field label{font-size:12px;color:#6b7280}.field select{padding:10px;border:1px solid #d1d5db;border-radius:9px;background:#fff}button{border:0;background:#111827;color:#fff;border-radius:10px;padding:11px 15px;cursor:pointer}.item{border-left:4px solid #d1d5db}.warn{color:#92400e}.bad{color:#991b1b}.ok{color:#166534}.source{word-break:break-all}.evidence{background:#f9fafb;padding:10px;border-radius:9px;margin-top:8px;line-height:1.45}.banner{padding:12px 14px;border-radius:10px;background:#eff6ff;color:#1e3a8a;margin:12px 0}.error{background:#fee2e2;color:#991b1b}@media(max-width:700px){.top{flex-direction:column}.toolbar{align-items:stretch}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Financial Intelligence Digest</h1><p class="muted">Deterministic factual digest from persisted evidence only. No forecasting, language-model generation, or trading signals.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a></div></div>
<div class="card toolbar"><div class="field"><label>Lookback</label><select id="days"><option value="1">1 day</option><option value="3">3 days</option><option value="7" selected>7 days</option><option value="14">14 days</option><option value="30">30 days</option></select></div><div class="field"><label>Items / section</label><select id="limit"><option>10</option><option selected>20</option><option>30</option><option>50</option></select></div><button onclick="loadDigest()">Apply / Refresh</button><span id="updated" class="muted"></span></div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid"><div class="card"><div class="muted">Recent documents</div><div id="documents" class="metric">-</div></div><div class="card"><div class="muted">New quality-safe claims</div><div id="claims" class="metric">-</div></div><div class="card"><div class="muted">Detected changes</div><div id="changes" class="metric">-</div></div><div class="card"><div class="muted">Conflicts</div><div id="conflicts" class="metric warn">-</div></div><div class="card"><div class="muted">Operator incidents</div><div id="incidents" class="metric">-</div></div></div>
<div id="safety" class="banner"></div>
<h2>New evidence</h2><div id="evidence"></div>
<h2>Factual changes</h2><div id="changeList"></div>
<h2>Conflicts</h2><div id="conflictList"></div>
<h2>Operator incidents</h2><div id="incidentList"></div>
<h2>Recent documents</h2><div id="documentList"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function claimCard(c){const u=safeUrl(c.source_url);return `<section class="card item"><strong>${esc(c.entity)} — ${esc(c.metric)}</strong><div class="metric">${esc(c.value_text)} ${esc(c.unit||'')}</div><div class="muted">${esc(c.source_id).toUpperCase()} · ${esc(c.state)} · date ${esc(c.temporal_date)}</div><div class="evidence">${esc(c.evidence_excerpt)}</div>${u?`<p><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">Open source</a></p>`:''}</section>`;}
function changeCard(c){return `<section class="card item"><strong>${esc(c.entity)} — ${esc(c.canonical_metric)}</strong><div>${esc(c.previous.value_text)} → <strong>${esc(c.current.value_text)}</strong></div><div class="muted">${esc(c.change_kind)} · ${esc(c.direction)} · ${esc(c.current.temporal_date)} · ${esc(c.current.source_id).toUpperCase()}</div></section>`;}
function incidentCard(i){return `<section class="card item"><strong>${esc(i.severity).toUpperCase()} · ${esc(i.title)}</strong><div class="muted">${esc(i.code)}${i.source_id?' · '+esc(i.source_id).toUpperCase():''}</div><p>${esc(i.detail)}</p></section>`;}
function documentCard(d){const u=safeUrl(d.source_url);return `<section class="card item"><strong>${esc(d.source_id).toUpperCase()} · ${esc(d.title||d.document_id)}</strong><div class="muted">${esc(d.retrieved_at)} · ${esc(d.content_type)} · ${esc(d.chunk_count)} chunks · ${esc(d.status)}</div>${u?`<p><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">Open source</a></p>`:''}</section>`;}
async function loadDigest(){const err=document.getElementById('err');err.style.display='none';try{const q=new URLSearchParams({lookback_days:days.value,limit:limit.value});const r=await fetch('/dashboard/digest/status?'+q.toString(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();documents.textContent=d.summary.recent_documents;claims.textContent=d.summary.new_quality_safe_active_claims;changes.textContent=d.summary.detected_changes;conflicts.textContent=d.summary.conflicted_claims;incidents.textContent=d.summary.operator_incidents;incidentList.innerHTML=d.incidents.map(incidentCard).join('')||'<div class="card muted">No operator incidents in the current readiness snapshot.</div>';evidence.innerHTML=d.new_evidence.map(claimCard).join('')||'<div class="card muted">No quality-safe dated active claims in this lookback window.</div>';changeList.innerHTML=d.changes.map(changeCard).join('')||'<div class="card muted">No comparable factual changes in this lookback window.</div>';conflictList.innerHTML=d.conflicts.map(claimCard).join('')||'<div class="card muted">No conflicted claims in this lookback window.</div>';documentList.innerHTML=d.recent_documents.map(documentCard).join('')||'<div class="card muted">No indexed documents retrieved in this lookback window.</div>';safety.textContent=d.safety.note;updated.textContent='Generated: '+new Date(d.generated_at).toLocaleString();}catch(e){err.textContent='Digest could not be loaded: '+e.message;err.style.display='block';}}
loadDigest();
</script></body></html>'''


@router.get(
    "/dashboard/digest",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def digest_page() -> str:
    return DIGEST_HTML


@router.get(
    "/dashboard/digest/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def digest_status(
    response: Response,
    lookback_days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_intelligence_digest(lookback_days=lookback_days, limit=limit)
