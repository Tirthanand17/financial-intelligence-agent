from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.document_detail import build_document_detail

router = APIRouter()


DOCUMENT_DETAIL_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Document Evidence Detail</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav,button{background:#111827;color:white;border:0;padding:10px 14px;border-radius:9px;text-decoration:none;cursor:pointer}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.muted{color:#6b7280;font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.metric{font-size:24px;font-weight:800}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:end}.field{display:flex;flex-direction:column;gap:5px;flex:1;min-width:260px}.field input{padding:10px;border:1px solid #d1d5db;border-radius:9px}.claim{border-left:4px solid #d1d5db}.ok{border-left-color:#16a34a}.warn{border-left-color:#d97706}.bad{border-left-color:#dc2626}.evidence{background:#f9fafb;border-radius:9px;padding:10px;white-space:pre-wrap;line-height:1.45;font-size:13px}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;word-break:break-all}.row{padding:7px 0;border-bottom:1px solid #eef2f7}.row:last-child{border-bottom:0}.error{background:#fee2e2;color:#991b1b;padding:12px;border-radius:10px;margin-top:12px}@media(max-width:720px){.top{flex-direction:column}.toolbar{align-items:stretch}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Document Evidence Detail</h1><p class="muted">Read-only provenance, structured claims, attribution, verification, trust, and supersession history for one indexed document.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a></div></div>
<div class="card toolbar"><div class="field"><label for="documentId" class="muted">Document ID</label><input id="documentId" placeholder="Enter indexed document ID"></div><button onclick="loadDocument()">Open document</button></div>
<div id="error" class="error" style="display:none"></div><div id="content" style="display:none">
<div class="card"><h2 id="title">Document</h2><div id="docMeta"></div></div>
<div class="grid"><div class="card"><div class="muted">Claims</div><div id="claimsCount" class="metric">-</div></div><div class="card"><div class="muted">Quality failures</div><div id="qualityCount" class="metric">-</div></div><div class="card"><div class="muted">Verification events</div><div id="verificationCount" class="metric">-</div></div><div class="card"><div class="muted">Trust events</div><div id="trustCount" class="metric">-</div></div></div>
<h2>Structured claims and audit history</h2><div id="claims"></div><p id="safety" class="muted"></p></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function claimHtml(c){const cls=c.quality_gate==='fail'?'bad':(c.state==='verified'||c.state==='trusted'?'ok':'warn');const attr=c.attribution?`${esc(c.attribution.basis)} · ${esc(c.attribution.canonical_entity)}`:'not recorded';const ver=(c.verification_events||[]).map(x=>`<div class="row">${esc(x.from_state)} → ${esc(x.to_state)} · ${esc(x.reason)} · ${esc(x.created_at)}</div>`).join('')||'<span class="muted">none</span>';const trust=(c.trust_events||[]).map(x=>`<div class="row">${esc(x.from_state)} → ${esc(x.to_state)} · ${esc(x.reason)} · ${esc(x.created_at)}</div>`).join('')||'<span class="muted">none</span>';const sup=c.superseded_by?`Superseded by ${esc(c.superseded_by.claim_id)}`:(c.supersedes||[]).length?`Supersedes ${(c.supersedes||[]).map(x=>esc(x.claim_id)).join(', ')}`:'No supersession edge';return `<section class="card claim ${cls}"><h3>${esc(c.entity)} — ${esc(c.metric)}</h3><div><strong>${esc(c.value_text)}</strong> ${esc(c.unit||'')} · ${esc(c.state)} · confidence ${esc(c.confidence)}</div><div class="muted">Publication ${esc(c.publication_date)} · Effective ${esc(c.effective_date)} · Quality ${esc(c.quality_gate)} ${c.quality_rejection_reason?'('+esc(c.quality_rejection_reason)+')':''}</div><div class="muted">Attribution: ${attr}</div><div class="muted">${sup}</div><h4>Evidence</h4><div class="evidence">${esc(c.evidence_text)}</div><h4>Verification events</h4>${ver}<h4>Trust events</h4>${trust}</section>`;}
async function loadDocument(){const id=documentId.value.trim();const err=document.getElementById('error');const body=document.getElementById('content');err.style.display='none';body.style.display='none';if(!id){err.textContent='Enter a document ID.';err.style.display='block';return;}try{const r=await fetch('/dashboard/document/'+encodeURIComponent(id)+'/status',{cache:'no-store'});if(r.status===404)throw new Error('Document not found');if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();title.textContent=d.document.title||d.document.document_id;const source=safeUrl(d.document.final_url||d.document.source_url);docMeta.innerHTML=`<div class="row"><strong>ID</strong><div class="mono">${esc(d.document.document_id)}</div></div><div class="row"><strong>Source</strong> ${esc(d.document.source_name)} (${esc(d.document.source_id)}) ${source?`· <a href="${esc(source)}" target="_blank" rel="noopener noreferrer">open source</a>`:''}</div><div class="row"><strong>SHA-256</strong><div class="mono">${esc(d.document.sha256)}</div></div><div class="row"><strong>B2 object key</strong><div class="mono">${esc(d.document.object_key)}</div></div><div class="row"><strong>Content</strong> ${esc(d.document.content_type)} · ${esc(d.document.chunk_count)} chunks · ${esc(d.document.status)}</div><div class="row"><strong>Retrieved</strong> ${esc(d.document.retrieved_at)}</div>`;claimsCount.textContent=d.summary.claims;qualityCount.textContent=d.summary.quality_failures;verificationCount.textContent=d.summary.verification_events;trustCount.textContent=d.summary.trust_events;claims.innerHTML=d.claims.map(claimHtml).join('')||'<div class="card muted">No structured claims were extracted from this document.</div>';safety.textContent=d.safety.note;body.style.display='block';history.replaceState(null,'','/dashboard/document/'+encodeURIComponent(id));}catch(e){err.textContent=e.message;err.style.display='block';}}
const parts=location.pathname.split('/').filter(Boolean);if(parts.length===3&&parts[0]==='dashboard'&&parts[1]==='document'){documentId.value=decodeURIComponent(parts[2]);loadDocument();}
</script></body></html>'''


@router.get(
    "/dashboard/document",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def document_detail_entry_page() -> str:
    return DOCUMENT_DETAIL_HTML


@router.get(
    "/dashboard/document/{document_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def document_detail_page(document_id: str = Path(min_length=1, max_length=128)) -> str:
    return DOCUMENT_DETAIL_HTML


@router.get(
    "/dashboard/document/{document_id}/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def document_detail_status(
    response: Response,
    document_id: str = Path(min_length=1, max_length=128),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    result = build_document_detail(document_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return result
