from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.provenance_graph import build_provenance_graph

router = APIRouter()


PROVENANCE_GRAPH_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Provenance Graph</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1280px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav,button{display:inline-block;background:#111827;color:#fff;border:0;padding:10px 14px;border-radius:10px;text-decoration:none;cursor:pointer}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin:14px 0}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.field{display:flex;flex-direction:column;gap:5px;flex:1;min-width:280px}.field label,.muted{color:#6b7280;font-size:13px}.field input{padding:10px;border:1px solid #d1d5db;border-radius:9px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.metric{font-size:26px;font-weight:800}.flow{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.node{border:1px solid #d1d5db;border-radius:10px;padding:10px;min-width:180px;background:#fff}.node strong{display:block}.source{border-left:4px solid #2563eb}.document{border-left:4px solid #7c3aed}.claim{border-left:4px solid #d97706}.verification_event{border-left:4px solid #0f766e}.trust_event{border-left:4px solid #16a34a}.entity_attribution{border-left:4px solid #0284c7}.discovery{border-left:4px solid #6b7280}.external_claim_reference{border-left:4px solid #dc2626}.edge{background:#f9fafb;border-radius:9px;padding:9px;margin:7px 0;font-size:13px;word-break:break-word}.pill{font-size:11px;font-weight:800;text-transform:uppercase;background:#eef2ff;border-radius:999px;padding:4px 7px}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px;margin:12px 0}.error{background:#fee2e2;color:#991b1b}@media(max-width:720px){.top{flex-direction:column}.toolbar{align-items:stretch}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Provenance Graph</h1><p class="muted">Read-only evidence lineage: source → document → claim → attribution / verification / trust / supersession relationships.</p></div><div><a class="nav" href="/dashboard/hub">Workspace</a> <a class="nav" href="/dashboard/document">Document Detail</a></div></div>
<div class="card toolbar"><div class="field"><label for="documentId">Document ID</label><input id="documentId" maxlength="128" placeholder="Enter an indexed document ID"></div><button onclick="loadGraph()">Build graph</button></div>
<div id="err" class="banner error" style="display:none"></div>
<div id="content" style="display:none"><div class="grid"><div class="card"><div class="muted">Nodes</div><div id="nodeCount" class="metric">-</div></div><div class="card"><div class="muted">Edges</div><div id="edgeCount" class="metric">-</div></div><div class="card"><div class="muted">Claims</div><div id="claimCount" class="metric">-</div></div><div class="card"><div class="muted">Verification events</div><div id="verificationCount" class="metric">-</div></div></div><h2>Nodes</h2><div id="nodes" class="flow"></div><h2>Relationships</h2><div class="card" id="edges"></div><div id="safety" class="banner"></div></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function nodeHtml(n){const m=n.metadata||{};let detail='';if(n.type==='document')detail=`SHA ${esc(m.sha256)} · ${esc(m.status)}`;else if(n.type==='claim')detail=`${esc(m.value_text)} ${esc(m.unit||'')} · ${esc(m.state)} · ${esc(m.quality_gate)}`;else if(n.type==='source')detail=`Authority ${esc(m.authority_level)} · ${esc(m.independence_group)}`;else detail=esc(m.reason||m.basis||m.status||'');return `<div class="node ${esc(n.type)}"><span class="pill">${esc(n.type)}</span><strong>${esc(n.label)}</strong><div class="muted">${detail}</div><div class="muted">${esc(n.id)}</div></div>`;}
function edgeHtml(e){return `<div class="edge"><strong>${esc(e.from)}</strong> → <strong>${esc(e.to)}</strong> <span class="pill">${esc(e.type)}</span> ${esc(e.label||'')}</div>`;}
async function loadGraph(){const id=documentId.value.trim(),err=document.getElementById('err'),content=document.getElementById('content');err.style.display='none';content.style.display='none';if(!id){err.textContent='Enter a document ID.';err.style.display='block';return;}try{const r=await fetch('/dashboard/provenance/'+encodeURIComponent(id)+'/status',{cache:'no-store'});if(r.status===404)throw new Error('Document not found');if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();nodeCount.textContent=d.summary.nodes;edgeCount.textContent=d.summary.edges;claimCount.textContent=d.summary.node_type_counts.claim||0;verificationCount.textContent=d.summary.node_type_counts.verification_event||0;nodes.innerHTML=d.nodes.map(nodeHtml).join('');edges.innerHTML=d.edges.map(edgeHtml).join('')||'<div class="muted">No relationships.</div>';safety.textContent=d.safety.note;content.style.display='block';history.replaceState(null,'','/dashboard/provenance/'+encodeURIComponent(id));}catch(e){err.textContent='Provenance graph could not be loaded: '+e.message;err.style.display='block';}}
const parts=location.pathname.split('/').filter(Boolean);if(parts.length===3&&parts[0]==='dashboard'&&parts[1]==='provenance'){documentId.value=decodeURIComponent(parts[2]);loadGraph();}
</script></body></html>'''


@router.get(
    "/dashboard/provenance",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def provenance_graph_entry_page() -> str:
    return PROVENANCE_GRAPH_HTML


@router.get(
    "/dashboard/provenance/{document_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def provenance_graph_page(document_id: str = Path(min_length=1, max_length=128)) -> str:
    return PROVENANCE_GRAPH_HTML


@router.get(
    "/dashboard/provenance/{document_id}/status",
    dependencies=[Depends(require_dashboard_auth)],
)
def provenance_graph_status(
    response: Response,
    document_id: str = Path(min_length=1, max_length=128),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    result = build_provenance_graph(document_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return result
