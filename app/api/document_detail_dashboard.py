from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.document_detail import build_document_detail

router = APIRouter()


DOCUMENT_DETAIL_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Document Evidence Detail</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1280px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav,button{background:#111827;color:#fff;border:0;padding:10px 14px;border-radius:9px;text-decoration:none;cursor:pointer}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.metric{font-size:24px;font-weight:800}.muted{color:#6b7280;font-size:13px}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.field{display:flex;flex-direction:column;gap:5px;flex:1;min-width:280px}.field input{padding:10px;border:1px solid #d1d5db;border-radius:9px}.row{padding:8px 0;border-bottom:1px solid #eef2f7}.row:last-child{border-bottom:0}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;word-break:break-all}.claim{border-left:4px solid #d1d5db}.claim.pass{border-left-color:#16a34a}.claim.fail{border-left-color:#dc2626}.evidence{white-space:pre-wrap;background:#f9fafb;padding:10px;border-radius:9px;line-height:1.45;font-size:13px}.pill{font-size:11px;font-weight:800;text-transform:uppercase;background:#eef2ff;border-radius:999px;padding:5px 8px}.head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.error{background:#fee2e2;color:#991b1b;padding:12px;border-radius:10px}.banner{background:#eff6ff;color:#1e3a8a;padding:12px;border-radius:10px}.source{word-break:break-all}@media(max-width:720px){.top,.head{flex-direction:column}.toolbar{align-items:stretch}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Document Evidence Detail</h1><p class="muted">Read-only provenance and structured claim audit history for one indexed document.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/search">Evidence Search</a></div></div>
<div class="card toolbar"><div class="field"><label class="muted" for="documentId">Document ID</label><input id="documentId" maxlength="128" placeholder="Enter an indexed document ID"></div><button onclick="loadDocument()">Open</button></div>
<div id="error" class="error" style="display:none"></div>
<div id="content" style="display:none">
  <div class="card"><div class="head"><div><h2 id="title">Document</h2><div id="sourceLine" class="muted"></div></div><span id="docStatus" class="pill"></span></div><div id="docMeta"></div></div>
  <div class="grid"><div class="card"><div class="muted">Claims</div><div id="claimsCount" class="metric">-</div></div><div class="card"><div class="muted">Quality failures</div><div id="qualityCount" class="metric">-</div></div><div class="card"><div class="muted">Verification events</div><div id="verificationCount" class="metric">-</div></div><div class="card"><div class="muted">Trust events</div><div id="trustCount" class="metric">-</div></div><div class="card"><div class="muted">Discovery links</div><div id="discoveryCount" class="metric">-</div></div></div>
  <div class="card"><h2>Discovery provenance</h2><div id="discoveries"></div></div>
  <h2>Structured claims and audit history</h2><div id="claims"></div>
  <div id="safety" class="banner"></div>
</div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function eventRows(items,kind){return (items||[]).map(x=>`<div class="row"><strong>${esc(x.from_state)} → ${esc(x.to_state)}</strong> · ${esc(x.reason)} · ${esc(x.created_at)}${kind==='verification'?`<div class="muted">supporting: ${esc((x.supporting_source_ids||[]).join(', ')||'none')} · conflicting: ${esc((x.conflicting_source_ids||[]).join(', ')||'none')}</div>`:`<div class="muted">corroborating: ${esc((x.corroborating_source_ids||[]).join(', ')||'none')}</div>`}</div>`).join('')||'<div class="muted">none</div>';}
function claimHtml(c){const attr=c.attribution?`${esc(c.attribution.basis)} · ${esc(c.attribution.canonical_entity)}`:'not recorded';const sup=c.superseded_by?`Superseded by ${esc(c.superseded_by.claim_id)}`:(c.supersedes||[]).length?`Supersedes ${(c.supersedes||[]).map(x=>esc(x.claim_id)).join(', ')}`:'No supersession edge';const source=safeUrl(c.source_url);return `<section class="card claim ${esc(c.quality_gate)}"><div class="head"><div><h3>${esc(c.entity)} — ${esc(c.metric)}</h3><div class="muted">Canonical: ${esc(c.canonical_metric)} · indicator ${esc(c.indicator_id||'unmapped exact source metric')} · ${esc(c.normalization_basis)}</div></div><span class="pill">${esc(c.state)}</span></div><div><strong>${esc(c.value_text)}</strong> ${esc(c.unit||'')} · confidence ${esc(c.confidence)}</div><div class="muted">Publication ${esc(c.publication_date)} · Effective ${esc(c.effective_date)} · chunk ${esc(c.evidence_chunk_index)} · Quality ${esc(c.quality_gate)} ${c.quality_rejection_reason?'('+esc(c.quality_rejection_reason)+')':''}</div><div class="muted">Attribution: ${attr}</div><div class="muted">${sup}</div><h4>Evidence</h4><div class="evidence">${esc(c.evidence_text)}</div>${source?`<p><a class="source" href="${esc(source)}" target="_blank" rel="noopener noreferrer">Open source evidence</a></p>`:''}<h4>Verification events</h4>${eventRows(c.verification_events,'verification')}<h4>Trust events</h4>${eventRows(c.trust_events,'trust')}</section>`;}
function discoveryHtml(x){const u=safeUrl(x.url);return `<div class="row"><strong>${esc(x.monitor_id)}</strong> · ${esc(x.status)} · seen ${esc(x.seen_count)} time(s) · attempts ${esc(x.attempt_count)}<div class="muted">Publication ${esc(x.publication_date)} · first ${esc(x.first_seen_at)} · last ${esc(x.last_seen_at)} · last error ${esc(x.last_error_code)}</div>${u?`<a class="source" href="${esc(u)}" target="_blank" rel="noopener noreferrer">Discovery URL</a>`:''}</div>`;}
async function loadDocument(){const id=documentId.value.trim(),err=document.getElementById('error'),body=document.getElementById('content');err.style.display='none';body.style.display='none';if(!id){err.textContent='Enter a document ID.';err.style.display='block';return;}try{const r=await fetch('/dashboard/document/'+encodeURIComponent(id)+'/status',{cache:'no-store'});if(r.status===404)throw new Error('Document not found');if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json(),doc=d.document;title.textContent=doc.title||doc.document_id;docStatus.textContent=doc.status;const source=safeUrl(doc.final_url)||safeUrl(doc.source_url);sourceLine.innerHTML=`${esc(doc.source_name)} (${esc(doc.source_id).toUpperCase()})${source?` · <a href="${esc(source)}" target="_blank" rel="noopener noreferrer">open source</a>`:''}`;docMeta.innerHTML=`<div class="row"><strong>Document ID</strong><div class="mono">${esc(doc.document_id)}</div></div><div class="row"><strong>SHA-256</strong><div class="mono">${esc(doc.sha256)}</div></div><div class="row"><strong>Content</strong> ${esc(doc.content_type)} · ${esc(doc.chunk_count)} chunks</div><div class="row"><strong>Retrieved</strong> ${esc(doc.retrieved_at)}</div><div class="row"><strong>Raw evidence retained</strong> ${doc.raw_evidence_retained?'yes':'no'} · internal object reference redacted: ${doc.object_reference_redacted?'yes':'no'}</div>`;claimsCount.textContent=d.summary.claims;qualityCount.textContent=d.summary.quality_failures;verificationCount.textContent=d.summary.verification_events;trustCount.textContent=d.summary.trust_events;discoveryCount.textContent=d.summary.discovery_links;discoveries.innerHTML=d.discoveries.map(discoveryHtml).join('')||'<div class="muted">No queue discovery record is linked to this document.</div>';claims.innerHTML=d.claims.map(claimHtml).join('')||'<div class="card muted">No structured claims were extracted from this document.</div>';safety.textContent=d.safety.note;body.style.display='block';history.replaceState(null,'','/dashboard/document/'+encodeURIComponent(id));}catch(e){err.textContent=e.message;err.style.display='block';}}
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
