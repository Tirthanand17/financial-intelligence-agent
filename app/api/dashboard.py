from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.core.config import get_settings
from app.dashboard import build_dashboard_snapshot
from app.services.intelligence import build_intelligence_snapshot

router = APIRouter()
security = HTTPBasic(auto_error=False)


def _auth_error(detail: str = "Authentication required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Basic"},
    )


def _credentials_match(
    credentials: HTTPBasicCredentials,
    *,
    username: str,
    password: str,
) -> bool:
    return secrets.compare_digest(credentials.username.encode(), username.encode()) and secrets.compare_digest(
        credentials.password.encode(), password.encode()
    )


def require_operator_auth(
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> None:
    """Require the existing operator identity for manual/private POST operations."""
    settings = get_settings()
    username = settings.dashboard_username
    password = settings.dashboard_password
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard authentication is not configured.",
        )
    if credentials is None:
        raise _auth_error()
    if not _credentials_match(credentials, username=username, password=password):
        raise _auth_error("Invalid dashboard credentials.")


def require_dashboard_auth(
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> None:
    """Require operator or optional inspection-only credentials for read surfaces.

    When no read-only identity is configured this preserves the historical single-
    operator behavior exactly. A partially configured read-only identity fails
    closed rather than silently changing the access model.
    """
    settings = get_settings()
    operator_username = settings.dashboard_username
    operator_password = settings.dashboard_password
    readonly_username = getattr(settings, "dashboard_readonly_username", None)
    readonly_password = getattr(settings, "dashboard_readonly_password", None)

    if not operator_username or not operator_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard authentication is not configured.",
        )

    readonly_user_set = bool((readonly_username or "").strip())
    readonly_password_set = bool((readonly_password or "").strip())
    if readonly_user_set != readonly_password_set:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Read-only dashboard authentication is incompletely configured.",
        )

    if credentials is None:
        raise _auth_error()

    if _credentials_match(
        credentials,
        username=operator_username,
        password=operator_password,
    ):
        return

    if readonly_user_set and readonly_username is not None and readonly_password is not None:
        if _credentials_match(
            credentials,
            username=readonly_username,
            password=readonly_password,
        ):
            return

    raise _auth_error("Invalid dashboard credentials.")


DASHBOARD_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Financial Intelligence Dashboard</title>
  <style>
    :root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1180px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center}.badge{padding:8px 12px;border-radius:999px;font-weight:700}.healthy{background:#dcfce7;color:#166534}.warning{background:#fef3c7;color:#92400e}.blocked{background:#fee2e2;color:#991b1b}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:18px 0}.card{background:white;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d}.muted{color:#6b7280;font-size:13px}.value{font-size:26px;font-weight:800;margin-top:4px}.row{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid #eef2f7}.row:last-child{border-bottom:0}button,.nav{border:0;background:#111827;color:white;border-radius:10px;padding:10px 14px;cursor:pointer;text-decoration:none;display:inline-block}table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}th,td{text-align:left;padding:11px 12px;border-bottom:1px solid #eef2f7;font-size:14px}th{background:#f9fafb}.ok{color:#166534;font-weight:700}.bad{color:#991b1b;font-weight:700}@media(max-width:700px){.top{align-items:flex-start;flex-direction:column}table{display:block;overflow-x:auto}}
  </style>
</head>
<body><main class="wrap">
  <div class="top"><div><h1>Financial Intelligence Agent</h1><div class="muted">Private read-only operational dashboard</div></div><div><span id="overall" class="badge">Loading…</span> <button onclick="loadStatus()">Refresh</button> <a class="nav" href="/dashboard/intelligence-view">Intelligence View</a></div></div>
  <div class="grid">
    <div class="card"><div class="muted">Documents</div><div id="documents" class="value">-</div></div>
    <div class="card"><div class="muted">Claims</div><div id="claims" class="value">-</div></div>
    <div class="card"><div class="muted">Qdrant points</div><div id="qdrant" class="value">-</div></div>
    <div class="card"><div class="muted">Pending queue</div><div id="pending" class="value">-</div></div>
    <div class="card"><div class="muted">Trust events</div><div id="trust" class="value">-</div></div>
    <div class="card"><div class="muted">Capacity</div><div id="capacity" class="value">-</div></div>
  </div>
  <div class="card"><h2>Source monitors</h2><div id="monitors"></div></div>
  <h2>Recent monitor runs</h2><table><thead><tr><th>Source</th><th>Outcome</th><th>Started</th><th>Discovered</th><th>Ingested</th><th>Error</th></tr></thead><tbody id="runs"></tbody></table>
  <p class="muted">Protected intelligence JSON: <code>/dashboard/intelligence</code>. It organizes persisted evidence only and does not generate trading signals.</p>
  <p id="updated" class="muted"></p><p id="note" class="muted"></p>
</main>
<script>
function esc(v){return String(v ?? '-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function fmtTime(v){if(!v)return '-';return new Date(v).toLocaleString();}
async function loadStatus(){
  const badge=document.getElementById('overall'); badge.textContent='Loading…'; badge.className='badge';
  try{
    const r=await fetch('/dashboard/status',{cache:'no-store'}); if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    badge.textContent=d.overall_status.toUpperCase(); badge.className='badge '+d.overall_status;
    documents.textContent=d.totals.documents; claims.textContent=d.totals.claims;
    qdrant.textContent=`${d.totals.actual_qdrant_points ?? '?'} / ${d.totals.expected_qdrant_points}`;
    pending.textContent=d.queue.pending; trust.textContent=d.totals.trust_events;
    capacity.textContent=d.capacity.safe?'SAFE':'BLOCKED'; capacity.className='value '+(d.capacity.safe?'ok':'bad');
    monitors.innerHTML=d.monitors.map(m=>`<div class="row"><span><strong>${esc(m.source_id.toUpperCase())}</strong><br><span class="muted">${esc(m.monitor_id)}</span></span><span class="${m.state==='ready'?'ok':'bad'}">${esc(m.state)}<br><span class="muted">${esc(fmtTime(m.last_success_at))}</span></span></div>`).join('');
    runs.innerHTML=d.recent_runs.map(x=>`<tr><td>${esc(x.source_id.toUpperCase())}</td><td>${esc(x.outcome)}</td><td>${esc(fmtTime(x.started_at))}</td><td>${esc(x.discovered_count)}</td><td>${esc(x.ingested_count)}</td><td>${esc(x.error_code)}</td></tr>`).join('');
    updated.textContent='Updated: '+fmtTime(d.generated_at); note.textContent=d.integrity_note;
  }catch(e){badge.textContent='UNAVAILABLE';badge.className='badge blocked';note.textContent='Dashboard status could not be loaded.';}
}
loadStatus(); setInterval(loadStatus,300000);
</script></body></html>'''


INTELLIGENCE_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Financial Intelligence Evidence View</title>
  <style>
    :root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1240px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none}.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:20px 0}.field{display:flex;flex-direction:column;gap:5px}.field label{font-size:12px;color:#6b7280}.field select,.field input{padding:10px;border:1px solid #d1d5db;border-radius:9px;background:white;min-width:150px}button{border:0;background:#111827;color:white;border-radius:10px;padding:11px 15px;cursor:pointer}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:14px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.safe{color:#166534}.warn{color:#92400e}.danger{color:#991b1b}.section-title{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-top:24px}.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{background:#eef2ff;border-radius:999px;padding:6px 10px;font-size:12px}.claim{border-left:4px solid #d1d5db}.claim.verified,.claim.trusted{border-left-color:#16a34a}.claim.conflicted{border-left-color:#dc2626}.claim.candidate{border-left-color:#d97706}.claim-head{display:flex;justify-content:space-between;gap:15px;align-items:flex-start}.state{font-size:12px;font-weight:800;text-transform:uppercase;padding:5px 8px;border-radius:999px;background:#f3f4f6}.value-text{font-size:20px;font-weight:750;margin:8px 0}.evidence{background:#f9fafb;padding:10px;border-radius:9px;margin-top:10px;font-size:13px;line-height:1.5}.source-link{word-break:break-all;font-size:12px}table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #eef2f7;font-size:13px}th{background:#f9fafb}.empty{padding:18px;text-align:center;color:#6b7280}.banner{padding:12px 14px;border-radius:10px;background:#fff7ed;color:#9a3412;margin:12px 0}.error{background:#fee2e2;color:#991b1b}@media(max-width:720px){.top,.claim-head{flex-direction:column}.toolbar{align-items:stretch}.field select,.field input{width:100%;box-sizing:border-box}table{display:block;overflow-x:auto}}
  </style>
</head>
<body><main class="wrap">
  <div class="top"><div><h1>Intelligence Evidence View</h1><p class="muted">Human-readable view of persisted, source-grounded evidence. Read-only; no forecasting or trading actions.</p></div><a class="nav" href="/dashboard">Operational Dashboard</a></div>
  <div class="toolbar card">
    <div class="field"><label for="sourceFilter">Source</label><select id="sourceFilter"><option value="">All sources</option></select></div>
    <div class="field"><label for="limitFilter">Items per section</label><select id="limitFilter"><option>8</option><option selected>12</option><option>20</option><option>30</option><option>50</option></select></div>
    <button onclick="loadIntelligence()">Apply / Refresh</button>
    <span id="generated" class="muted"></span>
  </div>
  <div id="loadError" class="banner error" style="display:none"></div>
  <div class="grid">
    <div class="card"><div class="muted">Documents</div><div id="sumDocuments" class="metric">-</div></div>
    <div class="card"><div class="muted">All claims</div><div id="sumClaims" class="metric">-</div></div>
    <div class="card"><div class="muted">Quality-safe active</div><div id="sumActive" class="metric">-</div></div>
    <div class="card"><div class="muted">Candidates</div><div id="sumCandidate" class="metric warn">-</div></div>
    <div class="card"><div class="muted">Verified / trusted</div><div id="sumVerified" class="metric safe">-</div></div>
    <div class="card"><div class="muted">Conflicts</div><div id="sumConflicts" class="metric danger">-</div></div>
    <div class="card"><div class="muted">Quality filtered</div><div id="sumFiltered" class="metric">-</div></div>
  </div>
  <div id="candidateNote" class="banner"></div>

  <div class="section-title"><h2>Source coverage</h2><div id="claimStates" class="chips"></div></div>
  <table><thead><tr><th>Source</th><th>Documents</th><th>Claims</th></tr></thead><tbody id="coverageRows"></tbody></table>

  <div class="section-title"><h2>Latest active claims</h2><span class="muted">Quality-safe, active structured evidence only</span></div>
  <div id="latestClaims"></div>

  <div class="section-title"><h2>Conflicts requiring attention</h2><span class="muted">No disputed value is promoted here</span></div>
  <div id="conflictClaims"></div>

  <div class="section-title"><h2>Recent indexed documents</h2><span class="muted">Source evidence retained by the ingestion system</span></div>
  <table><thead><tr><th>Source</th><th>Title</th><th>Type</th><th>Chunks</th><th>Retrieved</th><th>Status</th></tr></thead><tbody id="documentRows"></tbody></table>
  <p id="safetyNote" class="muted"></p>
</main>
<script>
function esc(v){return String(v ?? '-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function fmtTime(v){if(!v)return '-';return new Date(v).toLocaleString();}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function stateClass(v){const s=String(v||'').toLowerCase();return ['verified','trusted','conflicted','candidate'].includes(s)?s:'';}
function claimHtml(c){
  const url=safeUrl(c.source_url); const link=url?`<a class="source-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open source</a>`:'<span class="muted">Source URL unavailable</span>';
  return `<div class="card claim ${stateClass(c.state)}"><div class="claim-head"><div><strong>${esc(c.entity)}</strong><div class="muted">${esc(c.metric)}</div></div><span class="state">${esc(c.state)}</span></div><div class="value-text">${esc(c.value_text)}${c.unit?` <span class="muted">${esc(c.unit)}</span>`:''}</div><div class="muted">Confidence: ${esc(c.confidence)} · Publication: ${esc(c.publication_date)} · Effective: ${esc(c.effective_date)}</div><div class="evidence">${esc(c.evidence_excerpt)}</div><div style="margin-top:8px">${link}</div></div>`;
}
function populateSourceOptions(coverage){
  const select=document.getElementById('sourceFilter'); const current=select.value; const known=new Set(Array.from(select.options).map(o=>o.value));
  coverage.forEach(x=>{if(x.source_id&&!known.has(x.source_id)){const o=document.createElement('option');o.value=x.source_id;o.textContent=x.source_id.toUpperCase();select.appendChild(o);known.add(x.source_id);}}); select.value=current;
}
async function loadIntelligence(){
  const err=document.getElementById('loadError'); err.style.display='none';
  const source=document.getElementById('sourceFilter').value; const limit=document.getElementById('limitFilter').value;
  const qs=new URLSearchParams({limit}); if(source) qs.set('source_id',source);
  try{
    const r=await fetch('/dashboard/intelligence?'+qs.toString(),{cache:'no-store'}); if(!r.ok) throw new Error('HTTP '+r.status); const d=await r.json();
    const s=d.summary; sumDocuments.textContent=s.documents; sumClaims.textContent=s.claims; sumActive.textContent=s.active_quality_safe_claims; sumCandidate.textContent=s.candidate_claims; sumVerified.textContent=s.verified_or_trusted_claims; sumConflicts.textContent=s.conflicted_claims; sumFiltered.textContent=s.quality_filtered_claims;
    generated.textContent='Generated: '+fmtTime(d.generated_at); candidateNote.textContent=d.interpretation.candidate_warning;
    safetyNote.textContent=d.interpretation.safety_note;
    populateSourceOptions(d.source_coverage);
    claimStates.innerHTML=Object.entries(d.claim_states).map(([k,v])=>`<span class="chip">${esc(k)}: ${esc(v)}</span>`).join('')||'<span class="muted">No claims in scope</span>';
    coverageRows.innerHTML=d.source_coverage.map(x=>`<tr><td><strong>${esc(x.source_id.toUpperCase())}</strong></td><td>${esc(x.documents)}</td><td>${esc(x.claims)}</td></tr>`).join('')||'<tr><td colspan="3" class="empty">No source coverage in this scope.</td></tr>';
    latestClaims.innerHTML=d.latest_active_claims.map(claimHtml).join('')||'<div class="card empty">No active quality-safe claims in this scope.</div>';
    conflictClaims.innerHTML=d.conflicts.map(claimHtml).join('')||'<div class="card empty safe">No active conflicts in this scope.</div>';
    documentRows.innerHTML=d.recent_documents.map(x=>`<tr><td>${esc(x.source_id.toUpperCase())}</td><td>${esc(x.title)}</td><td>${esc(x.content_type)}</td><td>${esc(x.chunk_count)}</td><td>${esc(fmtTime(x.retrieved_at))}</td><td>${esc(x.status)}</td></tr>`).join('')||'<tr><td colspan="6" class="empty">No documents in this scope.</td></tr>';
  }catch(e){err.textContent='Intelligence data could not be loaded: '+e.message;err.style.display='block';}
}
loadIntelligence();
</script></body></html>'''


@router.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_dashboard_auth)])
def dashboard_page() -> str:
    return DASHBOARD_HTML


@router.get(
    "/dashboard/intelligence-view",
    response_class=HTMLResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
def dashboard_intelligence_view() -> str:
    return INTELLIGENCE_HTML


@router.get("/dashboard/status", dependencies=[Depends(require_dashboard_auth)])
def dashboard_status(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_dashboard_snapshot()


@router.get("/dashboard/intelligence", dependencies=[Depends(require_dashboard_auth)])
def dashboard_intelligence(
    response: Response,
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    limit: int = Query(default=12, ge=1, le=50),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_intelligence_snapshot(source_id=source_id, limit=limit)
