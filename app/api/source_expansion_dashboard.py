from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.sources.expansion_readiness import build_international_expansion_readiness

router = APIRouter()


SOURCE_EXPANSION_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Source Expansion Readiness</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1120px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:12px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}.muted{color:#6b7280;font-size:13px}.ok{color:#166534}.bad{color:#991b1b}.row{display:flex;justify-content:space-between;gap:12px;padding:7px 0;border-bottom:1px solid #eef2f7}.row:last-child{border-bottom:0}.pill{display:inline-block;padding:5px 8px;border-radius:999px;background:#eef2ff;font-size:11px;font-weight:800}.banner{padding:12px 14px;border-radius:10px;background:#fff7ed;color:#9a3412}a{word-break:break-word}@media(max-width:700px){.top{flex-direction:column}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>International Source Expansion Readiness</h1><p class="muted">Pre-activation governance only. Candidate APIs are not fetched, allow-lists are not widened, and no new source is added to the live scheduler.</p></div><a class="nav" href="/dashboard/hub">Workspace</a></div>
<div id="summary" class="banner">Loading…</div><div id="cards" class="grid"></div><div class="card"><h2>Activation boundary</h2><p id="safety" class="muted"></p></div>
<script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function safeUrl(v){try{const u=new URL(String(v));return u.protocol==='https:'?u.href:null;}catch(e){return null;}}
function candidateCard(c){const rows=Object.entries(c.checks).map(([k,v])=>`<div class="row"><span>${esc(k)}</span><strong class="${v?'ok':'bad'}">${v?'PASS':'BLOCK'}</strong></div>`).join('');const doc=safeUrl(c.documentation_url);return `<section class="card"><span class="pill">AUTHORITY ${esc(c.authority_level)}</span><h2>${esc(c.source_name)}</h2><p class="muted">${esc(c.api_standard)} · ${esc(c.api_host)}</p>${rows}<p><strong>Activation ready:</strong> <span class="${c.activation_ready?'ok':'bad'}">${c.activation_ready?'YES':'NO'}</span></p><p class="muted">Blockers: ${esc((c.activation_blockers||[]).join(', ')||'none')}</p>${doc?`<p><a href="${esc(doc)}" target="_blank" rel="noopener noreferrer">Official API documentation</a></p>`:''}</section>`;}
async function load(){const r=await fetch('/dashboard/source-expansion/status',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();summary.textContent=`Candidates: ${d.summary.candidate_count} · activation ready: ${d.summary.activation_ready} · blocked: ${d.summary.blocked} · live monitor additions: ${d.summary.live_monitor_additions}`;cards.innerHTML=d.candidates.map(candidateCard).join('');safety.textContent=d.safety.note;}
load().catch(e=>{summary.textContent='Readiness could not be loaded: '+e.message;});
</script></body></html>'''


@router.get(
    "/dashboard/source-expansion",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def source_expansion_page() -> str:
    return SOURCE_EXPANSION_HTML


@router.get(
    "/dashboard/source-expansion/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def source_expansion_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_international_expansion_readiness()
