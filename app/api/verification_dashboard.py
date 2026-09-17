from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from app.api.dashboard import require_dashboard_auth
from app.services.verification_workbench import build_verification_workbench

router = APIRouter()


VERIFICATION_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Claim Verification Workbench</title>
<style>
:root{font-family:Inter,system-ui,sans-serif;color:#111827;background:#f4f6f8}body{margin:0}.wrap{max-width:1280px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.nav{background:#111827;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}.card{background:white;border-radius:14px;padding:16px;box-shadow:0 2px 10px #0000000d;margin-bottom:12px}.metric{font-size:26px;font-weight:800}.muted{color:#6b7280;font-size:13px}.warn{color:#92400e}.ok{color:#166534}.bad{color:#991b1b}.toolbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.field{display:flex;flex-direction:column;gap:5px}.field label{font-size:12px;color:#6b7280}.toolbar select{padding:10px;border:1px solid #d1d5db;border-radius:9px;background:#fff;min-width:150px}button{border:0;background:#111827;color:white;border-radius:10px;padding:11px 15px;cursor:pointer}.item{border-left:4px solid #d1d5db}.item.conflict{border-left-color:#dc2626}.item.quality{border-left-color:#ea580c}.item.missing{border-left-color:#d97706}.item.support{border-left-color:#2563eb}.item.ready{border-left-color:#16a34a}.head{display:flex;justify-content:space-between;gap:15px}.pill{font-size:11px;font-weight:800;text-transform:uppercase;background:#f3f4f6;border-radius:999px;padding:5px 8px}.value{font-size:19px;font-weight:750;margin:8px 0}.evidence{background:#f9fafb;padding:10px;border-radius:9px;font-size:13px;line-height:1.5;margin-top:8px}.details{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:9px;margin-top:10px}.detail{background:#f9fafb;border-radius:9px;padding:9px;font-size:12px;line-height:1.5}.banner{background:#eff6ff;color:#1e3a8a;padding:12px 14px;border-radius:10px}.error{background:#fee2e2;color:#991b1b}.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{background:#eef2ff;padding:6px 9px;border-radius:999px;font-size:12px}.source-link{font-size:12px;word-break:break-all}@media(max-width:720px){.top,.head{flex-direction:column}.toolbar{align-items:stretch}.toolbar select{width:100%;box-sizing:border-box}}
</style></head><body><main class="wrap">
<div class="top"><div><h1>Claim Verification Workbench</h1><p class="muted">Read-only evidence diagnostics for candidate, verified, trusted, conflicted and historical claims.</p></div><div><a class="nav" href="/dashboard">Dashboard</a> <a class="nav" href="/dashboard/intelligence-view">Intelligence</a></div></div>
<div class="card toolbar">
  <div class="field"><label for="sourceFilter">Source</label><select id="sourceFilter"><option value="">All sources</option></select></div>
  <div class="field"><label for="stateFilter">Current state</label><select id="stateFilter"><option value="">All states</option><option>candidate</option><option>verified</option><option>trusted</option><option>conflicted</option><option>rejected</option><option>superseded</option></select></div>
  <div class="field"><label for="limit">Items</label><select id="limit"><option>20</option><option selected>50</option><option>100</option><option>200</option></select></div>
  <button onclick="loadData()">Apply / Refresh</button><span id="generated" class="muted"></span>
</div>
<div id="err" class="banner error" style="display:none"></div>
<div class="grid">
  <div class="card"><div class="muted">Claims in scope</div><div id="total" class="metric">-</div></div>
  <div class="card"><div class="muted">Actionable review</div><div id="actionable" class="metric warn">-</div></div>
  <div class="card"><div class="muted">Ready to verify</div><div id="ready" class="metric ok">-</div></div>
  <div class="card"><div class="muted">Trust-policy eligible</div><div id="trustEligible" class="metric ok">-</div></div>
  <div class="card"><div class="muted">Conflicts</div><div id="conflicts" class="metric bad">-</div></div>
  <div class="card"><div class="muted">Quality blocked</div><div id="qualityBlocked" class="metric warn">-</div></div>
  <div class="card"><div class="muted">Verification events</div><div id="events" class="metric">-</div></div>
  <div class="card"><div class="muted">Trust events</div><div id="trustEvents" class="metric">-</div></div>
</div>
<div class="banner" id="safety"></div>
<h2>Reason distribution</h2><div id="reasons" class="chips"></div>
<h2>Verification review queue</h2><div id="items"></div>
</main><script>
function esc(v){return String(v??'-').replace(/[&<>'\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));}
function fmtTime(v){if(!v)return '-';return new Date(v).toLocaleString();}
function safeUrl(v){try{const u=new URL(String(v));return (u.protocol==='https:'||u.protocol==='http:')?u.href:null;}catch(e){return null;}}
function klass(reason){return reason==='independent_sources_disagree'?'conflict':reason==='quality_gate_failed'?'quality':reason==='missing_temporal_scope'?'missing':reason==='insufficient_independent_sources'?'support':reason==='independent_sources_agree'?'ready':'';}
function list(v){return (v||[]).length?(v||[]).map(esc).join(', '):'none';}
function eventText(e){if(!e)return 'No recorded event';return `${esc(e.from_state)} → ${esc(e.to_state)} · ${esc(e.reason)} · ${esc(fmtTime(e.created_at))}`;}
function itemHtml(x){
  const url=safeUrl(x.source_url);const link=url?`<a class="source-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open source evidence</a>`:'<span class="muted">Source URL unavailable</span>';
  const sup=x.supersession?`Superseded by ${esc(x.supersession.superseded_by_claim_id)} (${esc(x.supersession.older_date)} → ${esc(x.supersession.newer_date)})`:(x.supersedes_claim_ids||[]).length?`Supersedes: ${list(x.supersedes_claim_ids)}`:'No supersession link';
  return `<div class="card item ${klass(x.verification_reason)}"><div class="head"><div><strong>${esc(x.entity)}</strong><div class="muted">${esc(x.metric)} · ${esc(x.source_id).toUpperCase()} · Authority ${esc(x.authority_level)} · Group ${esc(x.independence_group)}</div></div><span class="pill">${esc(x.verification_reason)}</span></div><div class="value">${esc(x.value_text)} ${esc(x.unit||'')}</div><div class="muted">Current ${esc(x.current_state)} → Safe reconciliation ${esc(x.safe_reconciled_state)} · Evidence assessment ${esc(x.evidence_assessed_state)} · Quality ${esc(x.quality_gate)} · Confidence ${esc(x.confidence)}</div><div class="details"><div class="detail"><strong>Independent evidence</strong><br>Supporting sources: ${list(x.supporting_source_ids)}<br>Supporting groups: ${list(x.supporting_independence_groups)}<br>Conflicting sources: ${list(x.conflicting_source_ids)}<br>Conflicting groups: ${list(x.conflicting_independence_groups)}</div><div class="detail"><strong>Trust diagnostic</strong><br>Assessment: ${esc(x.trust_diagnostic.assessed_state)}<br>Reason: ${esc(x.trust_diagnostic.reason)}<br>Corroboration: ${list(x.trust_diagnostic.corroborating_source_ids)}<br>Policy eligible: ${x.trust_diagnostic.policy_eligible_without_mutation?'yes':'no'}</div><div class="detail"><strong>Entity attribution</strong><br>Basis: ${esc(x.entity_attribution.basis)}<br>Source default: ${esc(x.entity_attribution.source_default_entity)}<br>Aliases: ${list(x.entity_attribution.matched_aliases)}<br>Ambiguous: ${list(x.entity_attribution.ambiguous_candidates)}</div><div class="detail"><strong>History</strong><br>Verification: ${eventText(x.latest_verification_event)}<br>Trust: ${eventText(x.latest_trust_event)}<br>${sup}</div></div><div class="evidence">${esc(x.evidence_excerpt)}</div><div style="margin-top:8px">${link}</div></div>`;
}
function populateSources(rows){const s=document.getElementById('sourceFilter');const current=s.value;const known=new Set(Array.from(s.options).map(o=>o.value));rows.forEach(x=>{if(x.source_id&&!known.has(x.source_id)){const o=document.createElement('option');o.value=x.source_id;o.textContent=`${x.source_id.toUpperCase()} · ${x.source_name}`;s.appendChild(o);known.add(x.source_id);}});s.value=current;}
async function loadData(){const e=document.getElementById('err');e.style.display='none';try{const qs=new URLSearchParams({limit:document.getElementById('limit').value});const source=document.getElementById('sourceFilter').value;const state=document.getElementById('stateFilter').value;if(source)qs.set('source_id',source);if(state)qs.set('state',state);const r=await fetch('/dashboard/verification/status?'+qs.toString(),{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();const s=d.summary;total.textContent=s.total_claims_in_scope;actionable.textContent=s.actionable_review_items;ready.textContent=s.ready_for_verification;trustEligible.textContent=s.trust_policy_eligible;conflicts.textContent=s.conflicted_claims;qualityBlocked.textContent=s.quality_blocked_claims;events.textContent=s.verification_events_in_scope;trustEvents.textContent=s.trust_events_in_scope;generated.textContent='Updated: '+fmtTime(d.generated_at);safety.textContent=d.safety.note;populateSources(d.available_sources);reasons.innerHTML=Object.entries(d.reason_counts).map(([k,v])=>`<span class="chip">${esc(k)}: ${esc(v)}</span>`).join('')||'<span class="muted">No reasons in scope.</span>';items.innerHTML=d.items.map(itemHtml).join('')||'<div class="card muted">No claims to display in this scope.</div>';}catch(err){e.textContent='Verification workbench could not be loaded: '+err.message;e.style.display='block';}}
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
    source_id: str | None = Query(default=None, min_length=2, max_length=64),
    state: str | None = Query(
        default=None,
        pattern="^(candidate|verified|trusted|rejected|conflicted|superseded)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return build_verification_workbench(source_id=source_id, state=state, limit=limit)
